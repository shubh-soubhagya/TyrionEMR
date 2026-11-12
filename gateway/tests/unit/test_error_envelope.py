import json

import pytest

from app.core import errors
from app.core.context import request_id_var
from app.core.errors import envelope, status_code_name


def test_envelope_shape():
    token = request_id_var.set("req-abc123")
    try:
        assert envelope("X", "msg", [{"a": 1}]) == {
            "error": {"code": "X", "message": "msg", "details": [{"a": 1}], "request_id": "req-abc123"}}
    finally:
        request_id_var.reset(token)


def test_details_default_to_empty_list():
    assert envelope("X", "m")["error"]["details"] == []


@pytest.mark.parametrize(
    ("exc", "status", "code"),
    [
        (errors.InvalidPath(), 400, "INVALID_PATH"),
        (errors.Unauthenticated(), 401, "UNAUTHENTICATED"),
        (errors.TokenExpired(), 401, "TOKEN_EXPIRED"),
        (errors.OriginNotAllowed(), 403, "ORIGIN_NOT_ALLOWED"),
        (errors.NotFound(), 404, "NOT_FOUND"),
        (errors.MethodNotAllowed(), 405, "METHOD_NOT_ALLOWED"),
        (errors.PayloadTooLarge(1024), 413, "PAYLOAD_TOO_LARGE"),
        (errors.UriTooLong(), 414, "URI_TOO_LONG"),
        (errors.RateLimited("auth_login", 7), 429, "RATE_LIMITED"),
        (errors.UpstreamUnavailable("lab"), 502, "UPSTREAM_UNAVAILABLE"),
        (errors.UpstreamNotDeployed("ai"), 503, "UPSTREAM_NOT_DEPLOYED"),
        (errors.GatewayBusy("ai"), 503, "GATEWAY_BUSY"),
        (errors.NotReady(), 503, "NOT_READY"),
        (errors.UpstreamTimeout("ai"), 504, "UPSTREAM_TIMEOUT"),
    ],
)
def test_catalog(exc, status, code):
    assert (exc.status_code, exc.code) == (status, code)


def test_rate_limited_carries_retry_after_and_policy():
    exc = errors.RateLimited("auth_login", 7)
    assert exc.headers == {"Retry-After": "7"}
    assert exc.details == [{"policy": "auth_login"}]
    assert "7 seconds" in exc.message


def test_upstream_errors_name_the_upstream():
    assert errors.UpstreamTimeout("ai").details == [{"upstream": "ai"}]


def test_upstream_error_keeps_status_and_never_uses_internal_error():
    exc = errors.UpstreamError("patient", 500)
    assert (exc.status_code, exc.code) == (500, "UPSTREAM_ERROR")
    assert exc.message == "The service returned an unexpected error."
    assert exc.details == [{"upstream": "patient", "upstream_status": 500}]
    assert errors.UpstreamError("patient", 503).status_code == 503
    assert errors.InternalError.code == "INTERNAL_ERROR"


def test_status_code_map_includes_413_and_414():
    assert status_code_name(413) == "PAYLOAD_TOO_LARGE"
    assert status_code_name(414) == "URI_TOO_LONG"
    assert status_code_name(418) == "HTTP_ERROR"


async def test_unknown_path_gets_the_envelope(client):
    r = await client.get("/nope")
    assert r.status_code == 404
    body = r.json()["error"]
    assert body["code"] == "NOT_FOUND" and body["request_id"] == r.headers["x-request-id"]


async def test_last_resort_500_is_an_envelope(settings):
    import httpx
    from fastapi import APIRouter

    from app.main import create_app

    app = create_app(settings)
    router = APIRouter()

    @router.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret detail that must not leak")

    app.include_router(router)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/boom")
    assert r.status_code == 500
    assert json.loads(r.content)["error"]["code"] == "INTERNAL_ERROR"
    assert "secret detail" not in r.text
    assert r.headers["x-request-id"].startswith("req-")
