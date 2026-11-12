import httpx

from tests.asgi_raw import call

BASE = {"x-content-type-options": "nosniff", "x-frame-options": "DENY", "referrer-policy": "no-referrer",
        "cross-origin-resource-policy": "same-site"}


def has_base(headers) -> bool:
    return all(headers.get(k) == v for k, v in BASE.items())


async def test_on_success_errors_probes_and_cors_responses(pipe):
    preflight = {"Origin": "http://localhost:4200", "Access-Control-Request-Method": "GET"}
    responses = [
        await pipe.client.get("/api/patients", headers=pipe.auth),                                  # proxied 200
        await pipe.client.get("/api/patients"),                                                      # 401
        await pipe.client.get("/api/internal/x"),                                                    # 404
        await pipe.client.get("/health"),                                                            # gateway-owned
        await pipe.client.options("/api/patients", headers=preflight),                               # 204
        await pipe.client.post("/api/patients", content=b"{}", headers={"Origin": "http://evil.example"}),   # 403
    ]
    assert [r.status_code for r in responses] == [200, 401, 404, 200, 204, 403]
    assert all(has_base(r.headers) for r in responses)


async def test_cache_control_no_store_by_default(pipe):
    r = await pipe.client.get("/api/patients", headers=pipe.auth)
    assert r.headers["cache-control"] == "no-store"


async def test_a_services_own_cache_control_and_etag_survive(pipe):
    pipe.ups["lab"]._handler = lambda req: httpx.Response(
        200, json={}, headers={"Cache-Control": "public, max-age=3600", "ETag": '"cat-v1"'})
    r = await pipe.client.get("/api/labs/catalog", headers=pipe.auth)
    assert r.headers["cache-control"] == "public, max-age=3600" and r.headers["etag"] == '"cat-v1"'
    assert has_base(r.headers)


async def test_hsts_only_when_enabled(make_pipe):
    off = await make_pipe()
    assert "strict-transport-security" not in (await off.client.get("/health")).headers
    on = await make_pipe(hsts_enabled=True)
    assert (await on.client.get("/health")).headers["strict-transport-security"] == "max-age=31536000"


async def test_the_gateway_never_adds_a_duplicate_header(pipe):
    pipe.ups["patient"]._handler = lambda req: httpx.Response(200, json={}, headers={"X-Frame-Options": "SAMEORIGIN"})
    r = await pipe.client.get("/api/patients", headers=pipe.auth)
    assert len(r.headers.get_list("x-frame-options")) == 1


async def test_a_gateway_500_still_has_security_headers(pipe):
    def explode(*a, **k):
        raise RuntimeError("x")

    pipe.app.state.pipeline.handle = explode
    r = await call(pipe.app, "GET", "/api/patients", headers=list(pipe.auth.items()))
    assert r.status == 500 and r.header("x-content-type-options") == "nosniff"
