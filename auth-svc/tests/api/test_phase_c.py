"""Items 14, 15, 16: non-UUID subject, graceful shutdown, pool metrics."""
import logging
import re
import uuid
from pathlib import Path

import jwt
import pytest

from tests.conftest import GOOD_PASSWORD, make_settings

pytestmark = pytest.mark.api
ROOT = Path(__file__).resolve().parents[2]


def signed(app, sub, role="clinician"):
    """A CORRECTLY signed token (right key, issuer, audience, times) with an arbitrary subject."""
    now = int(app.state.clock().timestamp())
    ks = app.state.keystore
    return jwt.encode({"iss": "nephro-auth", "aud": "nephro-api", "sub": sub, "role": role, "iat": now, "nbf": now,
                       "exp": now + 900, "jti": uuid.uuid4().hex}, ks.active.private_key, algorithm="RS256",
                      headers={"kid": ks.active.kid})


@pytest.mark.parametrize("sub", ["abc", "", "1234", "not-a-uuid-at-all", "' OR 1=1 --"])
async def test_non_uuid_subject_is_401_not_500(client, app, sub):
    r = await client.get("/auth/me", headers={"authorization": "Bearer " + signed(app, sub)})
    assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_non_uuid_subject_is_401_on_every_protected_route(client, app):
    h = {"authorization": "Bearer " + signed(app, "abc"), "origin": "http://localhost:4200"}
    r = await client.post("/auth/password", json={"current_password": "x", "new_password": "y"}, headers=h)
    assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_a_valid_uuid_subject_still_works(client, app, make_user):
    user = await make_user()
    r = await client.get("/auth/me", headers={"authorization": "Bearer " + signed(app, str(user.id))})
    assert r.status_code == 200


# ----------------------------------------------------------------------------- 15 graceful shutdown
async def test_shutdown_cancels_and_awaits_the_cleanup_task(migrated_db, rsa_key, clock):
    from app.main import create_app
    from app.services.keystore import KeyStore, SigningKey, thumbprint_kid

    pub = rsa_key.public_key()
    kid = thumbprint_kid(pub)
    app = create_app(make_settings(auth_database_url=migrated_db), clock,
                     KeyStore(SigningKey(kid, rsa_key), {kid: pub}))
    root_handlers = logging.getLogger().handlers[:]
    try:
        async with app.router.lifespan_context(app):
            task = app.state.cleanup_task
            assert not task.done()
        assert task.done() and task.cancelled()          # finished unwinding before the pool was closed
    finally:
        logging.getLogger().handlers[:] = root_handlers  # the lifespan reconfigures logging


def test_entrypoint_and_compose_leave_time_to_drain():
    assert "--timeout-graceful-shutdown 20" in (ROOT / "scripts" / "entrypoint.sh").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert re.search(r"stop_grace_period:\s*25s", compose)


# ----------------------------------------------------------------------------- 16 pool metrics
def gauge(text, name):
    m = re.search(rf"^{name}\s+([0-9.]+)", text, re.M)
    assert m, f"{name} missing from /metrics"
    return float(m.group(1))


async def test_pool_gauges_follow_the_live_pool(client, app, make_user):
    await make_user()
    await client.post("/auth/login", json={"email": "dr.rao@nephrocare.demo", "password": GOOD_PASSWORD})
    idle = await client.get("/metrics")
    assert gauge(idle.text, "auth_db_pool_size") >= 1
    base = gauge(idle.text, "auth_db_pool_checked_out")

    async with app.state.engine.connect() as held:        # a connection in use while Prometheus scrapes
        await held.exec_driver_sql("SELECT 1")
        busy = await client.get("/metrics")
        assert gauge(busy.text, "auth_db_pool_checked_out") >= base + 1
    after = await client.get("/metrics")
    assert gauge(after.text, "auth_db_pool_checked_out") == base
