import logging

import httpx
import pytest

from tests.asgi_raw import call

ORIGIN = "http://localhost:4200"
PREFLIGHT = {"Origin": ORIGIN, "Access-Control-Request-Method": "POST",
             "Access-Control-Request-Headers": "authorization,content-type"}


def acao(r: httpx.Response) -> str | None:
    return r.headers.get("access-control-allow-origin")


async def test_preflight_is_answered_by_the_gateway_and_never_forwarded(pipe):
    r = await pipe.client.options("/api/auth/login", headers=PREFLIGHT)
    assert r.status_code == 204 and r.content == b""
    h = r.headers
    assert h["access-control-allow-origin"] == ORIGIN and h["access-control-allow-credentials"] == "true"
    assert h["access-control-allow-methods"] == "GET, POST, PUT, PATCH, DELETE"
    allow = h["access-control-allow-headers"]
    assert "Authorization" in allow and "Idempotency-Key" in allow
    assert h["access-control-max-age"] == "600" and h["vary"] == "Origin"
    assert all(not rec.requests for rec in pipe.ups.values())


async def test_preflight_needs_no_token_and_consumes_no_rate_limit(pipe):
    for _ in range(300):
        assert (await pipe.client.options("/api/patients", headers=PREFLIGHT)).status_code == 204
    assert (await pipe.client.get("/api/patients", headers=pipe.auth)).status_code == 200


@pytest.mark.parametrize("origin", ["http://evil.example", "http://localhost:4201", "https://localhost:4200", "null"])
async def test_foreign_origin_preflight_is_403_without_cors_headers(pipe, origin):
    r = await pipe.client.options("/api/patients", headers={**PREFLIGHT, "Origin": origin})
    assert r.status_code == 403 and r.json()["error"]["code"] == "ORIGIN_NOT_ALLOWED"
    assert acao(r) is None and "access-control-allow-credentials" not in r.headers


@pytest.mark.parametrize("method", ["TRACE", "PO", "GETX", "CONNECT", "HEAD"])
async def test_preflight_for_a_method_the_gateway_does_not_allow_is_rejected(pipe, method):
    r = await pipe.client.options("/api/patients", headers={**PREFLIGHT, "Access-Control-Request-Method": method})
    assert r.status_code == 403


async def test_error_responses_carry_acao_so_the_browser_can_read_them(pipe):
    for path, status in (("/api/patients", 401), ("/api/internal/x", 404), ("/api/labs/%2e%2e/x", 400)):
        r = await call(pipe.app, "GET", path, headers=[("Origin", ORIGIN)])
        got = next((v for k, v in r.headers if k == "access-control-allow-origin"), None)
        assert r.status == status and got == ORIGIN, path


async def test_503_502_429_and_500_carry_acao_too(make_pipe):
    p = await make_pipe(lab_svc_url="")
    h = {"Origin": ORIGIN}
    assert acao(await p.client.get("/api/labs/x", headers={**p.auth, **h})) == ORIGIN                  # 503

    def refuse(request):
        raise httpx.ConnectError("x")

    p.ups["patient"]._handler = refuse
    assert acao(await p.client.get("/api/patients", headers={**p.auth, **h})) == ORIGIN                # 502
    for _ in range(5):
        await p.client.post("/api/auth/login", content=b"{}", headers=h)
    r = await p.client.post("/api/auth/login", content=b"{}", headers=h)
    assert r.status_code == 429 and acao(r) == ORIGIN and r.headers["retry-after"]                     # 429

    def explode(*a, **k):
        raise RuntimeError("bug")

    p.app.state.pipeline._proxy.forward = explode
    r = await p.client.get("/api/patients", headers={**p.auth, **h})
    assert r.status_code == 500 and acao(r) == ORIGIN and r.json()["error"]["code"] == "INTERNAL_ERROR"


async def test_success_responses_expose_the_headers_angular_needs(pipe):
    r = await pipe.client.get("/api/patients", headers={**pipe.auth, "Origin": ORIGIN})
    assert acao(r) == ORIGIN and r.headers["access-control-allow-credentials"] == "true"
    exposed = r.headers["access-control-expose-headers"]
    assert all(n in exposed for n in ("X-Request-ID", "Retry-After", "ETag", "Location", "Content-Disposition"))


async def test_vary_origin_is_on_every_response_even_without_an_origin(pipe):
    for r in (await pipe.client.get("/api/patients", headers=pipe.auth), await pipe.client.get("/health"),
              await pipe.client.get("/api/nope")):
        assert "Origin" in r.headers.get_list("vary")


async def test_no_origin_header_is_processed_normally_without_cors_headers(pipe):
    r = await pipe.client.post("/api/patients", content=b"{}", headers=pipe.auth)
    assert r.status_code == 200 and acao(r) is None


async def test_foreign_origin_unsafe_method_is_blocked_before_anything_runs(pipe):
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        r = await pipe.client.request(method, "/api/patients", headers={**pipe.auth, "Origin": "http://evil.example"})
        assert r.status_code == 403 and r.json()["error"]["code"] == "ORIGIN_NOT_ALLOWED"
    assert not pipe.ups["patient"].requests


async def test_foreign_origin_get_is_processed_but_the_browser_cannot_read_it(pipe):
    r = await pipe.client.get("/api/patients", headers={**pipe.auth, "Origin": "http://evil.example"})
    assert r.status_code == 200 and acao(r) is None
    assert "access-control-allow-credentials" not in r.headers


async def test_foreign_origin_login_is_blocked(pipe):
    r = await pipe.client.post("/api/auth/login", content=b"{}", headers={"Origin": "http://evil.example"})
    assert r.status_code == 403 and not pipe.ups["auth"].requests


async def test_origin_is_forwarded_to_auth_svc_for_its_own_check(pipe):
    await pipe.client.post("/api/auth/refresh", content=b"{}", headers={"Origin": ORIGIN})
    assert pipe.ups["auth"].last.headers["origin"] == ORIGIN


async def test_several_allowed_origins(make_pipe):
    p = await make_pipe(cors_allowed_origins="https://emr.example.org,https://admin.example.org")
    for o in ("https://emr.example.org", "https://admin.example.org"):
        assert acao(await p.client.get("/api/patients", headers={**p.auth, "Origin": o})) == o
    assert acao(await p.client.get("/api/patients", headers={**p.auth, "Origin": ORIGIN})) is None


async def test_route_labels_for_preflight_and_rejection(pipe, caplog):
    with caplog.at_level(logging.INFO, logger="nephro.access"):
        await pipe.client.options("/api/patients", headers=PREFLIGHT)
        await pipe.client.post("/api/patients", content=b"{}", headers={"Origin": "http://evil.example"})
    labels = [r.route for r in caplog.records if r.name == "nephro.access"]
    assert labels == ["preflight", "origin_rejected"]


async def test_cors_rejection_carries_a_request_id(pipe):
    r = await pipe.client.post("/api/patients", content=b"{}", headers={"Origin": "http://evil.example"})
    assert r.json()["error"]["request_id"] == r.headers["x-request-id"]
