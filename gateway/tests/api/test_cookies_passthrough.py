import httpx

from tests.proxy_harness import Recorder

COOKIES = [("Set-Cookie", "nephro_rt=abc; Path=/api/auth; HttpOnly; Secure; SameSite=Strict"),
           ("Set-Cookie", "other=1; Path=/api/auth")]


def with_cookies(request):
    return httpx.Response(200, json={}, headers=COOKIES)


async def test_multiple_set_cookie_headers_survive_on_auth_routes(gw):
    client, ups = gw
    ups["auth"]._handler = with_cookies
    r = await client.post("/api/auth/login", content=b"{}")
    assert r.headers.get_list("set-cookie") == [v for _, v in COOKIES]      # unchanged, never merged


async def test_set_cookie_is_dropped_on_every_other_route(gw):
    client, ups = gw
    for name, path in [("patient", "/api/patients"), ("lab", "/api/labs/x"), ("ai", "/api/ai/x")]:
        ups[name]._handler = with_cookies
        r = await client.get(path)
        assert r.status_code == 200 and "set-cookie" not in r.headers


async def test_request_cookie_is_forwarded_to_auth_only(gw):
    client, ups = gw
    client.cookies.clear()
    headers = {"Cookie": "nephro_rt=secret-refresh"}
    await client.post("/api/auth/refresh", headers=headers)
    await client.get("/api/patients", headers=headers)
    await client.get("/api/labs/x", headers=headers)
    assert ups["auth"].last.headers["cookie"] == "nephro_rt=secret-refresh"
    assert "cookie" not in ups["patient"].last.headers and "cookie" not in ups["lab"].last.headers


async def test_origin_is_forwarded_for_the_auth_origin_check(gw):
    client, ups = gw
    await client.post("/api/auth/refresh", headers={"Origin": "http://localhost:4200"})
    assert ups["auth"].last.headers["origin"] == "http://localhost:4200"


async def test_auth_rate_limit_and_busy_errors_from_auth_svc_pass_through(gw):
    """auth-svc's own 429 RATE_LIMITED / 503 SERVICE_BUSY are the inner layer and arrive unchanged."""
    client, ups = gw
    body = {"error": {"code": "RATE_LIMITED", "message": "Too many requests. Please slow down.",
                      "details": [], "request_id": "x"}}
    ups["auth"]._handler = lambda req: httpx.Response(429, json=body, headers={"Retry-After": "7"})
    r = await client.post("/api/auth/login", content=b"{}")
    assert r.status_code == 429 and r.json() == body and r.headers["retry-after"] == "7"
    assert isinstance(ups["auth"], Recorder)
