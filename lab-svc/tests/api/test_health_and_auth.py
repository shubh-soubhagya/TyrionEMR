"""Phase 2 done-when: /health 200, /ready 200 (and fails without DB), 401 without token, 403 wrong role."""
from __future__ import annotations

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from tests.conftest import make_settings


async def test_health_ok_without_auth(client):
    r = await client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}
    assert r.headers["x-request-id"].startswith("req-")


@pytest.mark.api
async def test_ready_ok_with_db_and_keys(client, migrated_db):
    r = await client.get("/ready")
    assert r.status_code == 200, r.text
    assert r.json()["jwks"] == 1


async def test_ready_fails_when_db_unreachable(app, jwks, settings, clock):
    from app.main import create_app
    bad = make_settings(lab_database_url="postgresql+asyncpg://x:x@127.0.0.1:1/x")
    app = create_app(bad, clock=clock, jwks=jwks)
    import httpx
    async with app.router.lifespan_context(app):
        await jwks.refresh("test")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            r = await c.get("/ready")
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "NOT_READY"
    assert "x:x" not in r.text and "127.0.0.1" not in r.text      # no connection details leak


async def test_ready_fails_without_jwks_keys(settings, clock):
    from app.main import create_app
    from app.services.jwks import JwksCache

    async def broken():
        raise RuntimeError("auth-svc down")

    import httpx
    app = create_app(settings, clock=clock, jwks=JwksCache(broken, settings))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            r = await c.get("/ready")
    assert r.status_code == 503
    assert {"check": "jwks", "status": "failed"} in r.json()["error"]["details"]


async def test_no_token_is_401(client):
    r = await client.get("/_probe/me")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "UNAUTHENTICATED"
    assert r.json()["error"]["request_id"] == r.headers["x-request-id"]


async def test_valid_clinician_token(client, sign):
    r = await client.get("/_probe/me", headers={"Authorization": f"Bearer {sign(name='Dr. Anita Rao')}"})
    assert r.status_code == 200
    assert "name" not in r.json()                  # a `name` claim is ignored: tokens carry no PII


async def test_token_without_name_claim_is_fine(client, sign):
    r = await client.get("/_probe/me", headers={"Authorization": f"Bearer {sign(name=None)}"})
    assert r.status_code == 200


@pytest.mark.parametrize("kwargs", [
    {"aud": "someone-else"}, {"iss": "evil"}, {"drop": ("exp",)}, {"drop": ("sub",)}, {"sub": "not-a-uuid"},
])
async def test_bad_claims_are_401(client, sign, kwargs):
    r = await client.get("/_probe/me", headers={"Authorization": f"Bearer {sign(**kwargs)}"})
    assert r.status_code == 401


async def test_expired_token_is_401(client, sign, clock):
    token = sign(ttl=60)
    clock.advance(seconds=60 + 31)                      # past exp + 30 s leeway
    r = await client.get("/_probe/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


async def test_token_signed_by_unknown_key_is_401(client, sign):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    r = await client.get("/_probe/me", headers={"Authorization": f"Bearer {sign(key=other)}"})
    assert r.status_code == 401


async def test_hs256_and_none_algorithms_rejected(client, rsa_key):
    for token in (jwt.encode({"sub": "x"}, "secret", algorithm="HS256"),
                  jwt.encode({"sub": "x"}, None, algorithm="none")):
        r = await client.get("/_probe/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401


async def test_malformed_authorization_header(client):
    for h in ("Bearer", "Basic abc", "Bearer   ", "garbage"):
        r = await client.get("/_probe/me", headers={"Authorization": h})
        assert r.status_code == 401


async def test_wrong_role_is_403(client, sign):
    r = await client.get("/_probe/me", headers={"Authorization": f"Bearer {sign(role='nurse')}"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN"


async def test_unknown_route_uses_envelope(client):
    r = await client.get("/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"


async def test_metrics_exposed(client):
    r = await client.get("/metrics")
    assert r.status_code == 200 and "http_request_duration_seconds" in r.text
