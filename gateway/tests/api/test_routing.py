import httpx
import pytest

UUID = "0b7c1e2a-4d5f-4a6b-8c7d-0e1f2a3b5a69"


@pytest.mark.parametrize(
    ("path", "upstream", "expected"),
    [
        ("/api/auth/me", "auth", "/auth/me"),
        ("/api/patients", "patient", "/patients"),
        ("/api/patients/", "patient", "/patients/"),
        (f"/api/patients/{UUID}/encounters", "patient", f"/patients/{UUID}/encounters"),
        ("/api/encounters", "patient", "/encounters"),
        (f"/api/labs/patients/{UUID}/trends", "lab", f"/labs/patients/{UUID}/trends"),
        ("/api/ai/summaries/7", "ai", "/ai/summaries/7"),
        ("/api/insights/abc", "ai", "/insights/abc"),
    ],
)
async def test_prefix_reaches_the_right_upstream_with_only_api_stripped(gw, path, upstream, expected):
    client, ups = gw
    r = await client.get(path, headers={"Authorization": "Bearer t"})
    assert r.status_code == 200
    assert ups[upstream].last.url.path == expected
    assert all(not rec.requests for name, rec in ups.items() if name != upstream)


async def test_method_query_and_body_pass_through(gw):
    client, ups = gw
    r = await client.post("/api/patients?x=1", content=b'{"a":1}', headers={"Content-Type": "application/json"})
    assert r.status_code == 200
    sent = ups["patient"].last
    assert sent.method == "POST" and sent.url.query == b"x=1"
    assert sent.content == b'{"a":1}' and sent.headers["content-type"] == "application/json"
    assert sent.headers["content-length"] == "7"


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE"])
async def test_other_methods(gw, method):
    client, ups = gw
    await client.request(method, "/api/patients/1")
    assert ups["patient"].last.method == method


async def test_gateway_sets_forwarding_headers_and_drops_spoofed_ones(gw):
    client, ups = gw
    await client.get("/api/patients", headers={"X-User-Id": "evil", "X-Forwarded-For": "1.2.3.4",
                                               "Authorization": "Bearer abc", "Origin": "http://localhost:4200"})
    h = ups["patient"].last.headers
    assert h["x-forwarded-for"] == "203.0.113.9" and h["x-forwarded-host"] == "localhost:8080"
    assert h["x-request-id"].startswith("req-") and h["accept-encoding"] == "identity"
    assert h["authorization"] == "Bearer abc" and h["origin"] == "http://localhost:4200"
    assert "x-user-id" not in h


async def test_request_id_is_propagated_upstream_and_not_taken_from_the_service_response(gw, upstreams):
    client, ups = gw
    ups["patient"]._handler = lambda req: httpx.Response(200, json={}, headers={"X-Request-ID": "svc-own"})
    r = await client.get("/api/patients", headers={"X-Request-ID": "req-from-browser"})
    assert ups["patient"].last.headers["x-request-id"] == "req-from-browser"
    assert r.headers["x-request-id"] == "req-from-browser"


async def test_unknown_prefix_is_404_and_traversal_is_400_in_the_envelope(gw):
    client, ups = gw
    assert (await client.get("/api/internal/patients/x/basic")).json()["error"]["code"] == "NOT_FOUND"
    assert (await client.get("/api/encountersX")).status_code == 404
    r = await client.get("/api/labs/%2e%2e/internal")
    assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_PATH"
    assert all(not rec.requests for rec in ups.values())


async def test_service_json_error_envelope_passes_through_untouched(gw):
    client, ups = gw
    body = {"error": {"code": "VERSION_CONFLICT", "message": "x", "details": [], "request_id": "svc"}}
    ups["patient"]._handler = lambda req: httpx.Response(409, json=body)
    r = await client.patch("/api/patients/1", json={})
    assert r.status_code == 409 and r.json() == body


async def test_redirect_is_not_followed_and_location_is_rewritten(gw):
    client, ups = gw
    ups["patient"]._handler = lambda req: httpx.Response(
        307, headers={"Location": "http://patient-svc:8000/patients/"})
    r = await client.get("/api/patients")
    assert r.status_code == 307 and r.headers["location"] == "/api/patients/"
    assert len(ups["patient"].requests) == 1


async def test_created_location_is_rewritten(gw):
    client, ups = gw
    ups["patient"]._handler = lambda req: httpx.Response(201, json={"id": 1}, headers={"Location": "/patients/1"})
    assert (await client.post("/api/patients", json={})).headers["location"] == "/api/patients/1"


async def test_204_and_304_have_no_body(gw):
    client, ups = gw
    ups["lab"]._handler = lambda req: httpx.Response(304, headers={"ETag": '"v1"'})
    r = await client.get("/api/labs/x", headers={"If-None-Match": '"v1"'})
    assert r.status_code == 304 and r.content == b"" and r.headers["etag"] == '"v1"'
    assert ups["lab"].last.headers["if-none-match"] == '"v1"'
    ups["lab"]._handler = lambda req: httpx.Response(204)
    assert (await client.delete("/api/labs/x")).status_code == 204


async def test_proxy_logs_upstream_fields_for_the_access_log(gw, caplog):
    import logging

    client, _ = gw
    with caplog.at_level(logging.INFO, logger="nephro.access"):
        await client.get("/api/patients?q=secret-search-text")
    rec = next(r for r in caplog.records if r.name == "nephro.access")
    assert rec.upstream == "patient" and rec.upstream_status == 200 and rec.upstream_ms is not None
    assert "secret-search-text" not in str(rec.__dict__)
