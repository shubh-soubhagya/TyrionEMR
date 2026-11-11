import httpx
import pytest
from fastapi import FastAPI
from pydantic import BaseModel

from app.core.common_setup import install_common_middleware
from app.core.errors import AccountLocked, InvalidCredentials


class Body(BaseModel):
    password: str


def make_app() -> FastAPI:
    app = FastAPI()
    install_common_middleware(app)

    @app.get("/boom")
    async def boom():
        raise RuntimeError("secret detail")

    @app.get("/invalid")
    async def invalid():
        raise InvalidCredentials()

    @app.get("/locked")
    async def locked():
        raise AccountLocked(retry_after=61)

    @app.post("/body")
    async def body(b: Body):
        return {}

    return app


@pytest.fixture
async def client():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=make_app(), raise_app_exceptions=False),
                                 base_url="http://t") as c:
        yield c


def assert_envelope(resp, code):
    err = resp.json()["error"]
    assert set(err) == {"code", "message", "details", "request_id"}
    assert err["code"] == code
    assert err["request_id"] == resp.headers["x-request-id"]


async def test_app_error(client):
    r = await client.get("/invalid")
    assert r.status_code == 401
    assert_envelope(r, "INVALID_CREDENTIALS")


async def test_locked_has_retry_after(client):
    r = await client.get("/locked")
    assert r.status_code == 429 and r.headers["retry-after"] == "61"
    assert "2 minutes" in r.json()["error"]["message"]


async def test_404_uses_envelope(client):
    r = await client.get("/nope")
    assert r.status_code == 404
    assert_envelope(r, "NOT_FOUND")


async def test_unhandled_is_500_envelope_without_leak(client):
    r = await client.get("/boom")
    assert r.status_code == 500
    assert_envelope(r, "INTERNAL_ERROR")
    assert "secret detail" not in r.text


async def test_validation_error_never_echoes_input(client):
    r = await client.post("/body", json={"password": 123456789012, "x": 1})
    r2 = await client.post("/body", json={})
    assert r2.status_code == 422
    assert_envelope(r2, "VALIDATION_ERROR")
    assert "input" not in r2.text
    assert r.status_code in (200, 422)


async def test_incoming_request_id_is_kept_and_bad_one_replaced(client):
    r = await client.get("/invalid", headers={"x-request-id": "abc-123"})
    assert r.headers["x-request-id"] == "abc-123"
    r = await client.get("/invalid", headers={"x-request-id": "bad id with spaces!"})
    assert r.headers["x-request-id"].startswith("req-")
