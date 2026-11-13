from __future__ import annotations

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.main import create_app
from tests.conftest import make_settings


def bare(client: httpx.AsyncClient) -> httpx.AsyncClient:
    """Same app, no Authorization header."""
    return httpx.AsyncClient(transport=client._transport, base_url="http://test")


async def test_health_needs_no_token(client: httpx.AsyncClient):
    r = await bare(client).get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}
    assert r.headers["x-request-id"].startswith("req-")


async def test_request_id_is_echoed(client: httpx.AsyncClient):
    r = await client.get("/health", headers={"X-Request-ID": "abc-123"})
    assert r.headers["x-request-id"] == "abc-123"


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer nonsense"}, {"Authorization": "Basic abc"}])
async def test_insights_without_valid_token_is_401(client: httpx.AsyncClient, headers):
    r = await bare(client).get("/insights/worklist", headers=headers)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_wrong_audience_is_401(client: httpx.AsyncClient, sign):
    r = await client.get("/insights/worklist", headers={"Authorization": f"Bearer {sign(aud='other')}"})
    assert r.status_code == 401


async def test_expired_token_is_401_token_expired(client: httpx.AsyncClient, sign):
    r = await client.get("/insights/worklist", headers={"Authorization": f"Bearer {sign(ttl=-120)}"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "TOKEN_EXPIRED"


async def test_non_clinician_is_403(client: httpx.AsyncClient, sign):
    r = await client.get("/insights/worklist", headers={"Authorization": f"Bearer {sign(role='admin')}"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN"


async def test_token_signed_by_an_unknown_key_is_401(client: httpx.AsyncClient, sign):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    r = await client.get("/insights/worklist", headers={"Authorization": f"Bearer {sign(key=other)}"})
    assert r.status_code == 401


@pytest.mark.api
async def test_ready_when_db_is_migrated(client: httpx.AsyncClient, db_engine):
    r = await client.get("/ready")
    assert r.status_code == 200, r.text
    assert r.json()["migrations"] == "head"


async def test_ready_fails_when_database_unreachable(clock, jwks, upstreams):
    app = create_app(make_settings(ai_database_url="postgresql+asyncpg://x:x@127.0.0.1:1/none"),
                     clock=clock, jwks=jwks)
    async with app.router.lifespan_context(app):
        await jwks.refresh("test")
        c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t")
        r = await c.get("/ready")
        assert r.status_code == 503
        assert {"db", "migrations"} <= {d["check"] for d in r.json()["error"]["details"]}
        assert "127.0.0.1" not in r.text             # connection details never leak



async def test_a_trailing_slash_is_a_404_not_a_redirect(client):
    resp = await client.get("/health/", follow_redirects=False)
    assert resp.status_code == 404
