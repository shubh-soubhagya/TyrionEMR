import pytest
from sqlalchemy import text

from app.api.routes.health import head_revision
from app.main import build_state, create_app
from tests.conftest import client_for, make_settings

pytestmark = pytest.mark.api


async def test_health_is_200(client):
    r = await client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


async def test_ready_reports_db_migrations_and_signing_key(client, app):
    r = await client.get("/ready")
    assert r.status_code == 200
    j = r.json()
    assert (j["status"], j["db"], j["migrations"]) == ("ready", "ok", "head")
    assert j["signing_key"] == app.state.keystore.active.kid


async def test_ready_is_503_when_migrations_are_not_at_head(client, app):
    async with app.state.sessionmaker() as s, s.begin():
        await s.execute(text("UPDATE alembic_version SET version_num = '0000'"))
    try:
        r = await client.get("/ready")
        assert r.status_code == 503 and r.json()["error"]["code"] == "NOT_READY"
        assert {"check": "migrations", "status": "failed"} in r.json()["error"]["details"]
    finally:
        async with app.state.sessionmaker() as s, s.begin():
            await s.execute(text("UPDATE alembic_version SET version_num = :v"), {"v": head_revision()})


async def test_ready_is_503_when_the_database_is_unreachable(migrated_db, rsa_key, clock):
    from app.services.keystore import KeyStore, SigningKey, thumbprint_kid
    bad = migrated_db.replace("@localhost:5433/", "@localhost:1/")
    s = make_settings(auth_database_url=bad)
    app = create_app(s, clock)
    pub = rsa_key.public_key()
    kid = thumbprint_kid(pub)
    build_state(app, s, clock, KeyStore(SigningKey(kid, rsa_key), {kid: pub}))
    try:
        async with client_for(app) as c:
            r = await c.get("/ready")
        assert r.status_code == 503
        assert any(d["check"] == "db" for d in r.json()["error"]["details"])
        assert "localhost" not in r.text and "password" not in r.text.lower()   # no connection details leak
    finally:
        await app.state.engine.dispose()


async def test_head_revision_matches_the_migration_files():
    assert head_revision() == "0001"


async def test_metrics_endpoint_exposes_auth_and_http_metrics(client, make_user):
    await make_user()
    await client.post("/auth/login", json={"email": "dr.rao@nephrocare.demo", "password": "Kidney2026care"})
    body = (await client.get("/metrics")).text
    for name in ("auth_login_total", "auth_argon2_seconds", "http_request_duration_seconds", "auth_refresh_total"):
        assert name in body
    assert 'route="/auth/login"' in body


async def test_every_error_uses_the_envelope(client):
    for r in (await client.get("/nope"), await client.post("/auth/login", json={}),
              await client.get("/auth/me"), await client.post("/auth/refresh")):
        err = r.json()["error"]
        assert set(err) == {"code", "message", "details", "request_id"} and err["request_id"]
