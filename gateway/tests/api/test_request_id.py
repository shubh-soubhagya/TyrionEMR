import re

RID = re.compile(r"^req-[0-9a-f]{12}$")


async def test_generated_when_absent_and_echoed(pipe):
    r = await pipe.client.get("/api/patients", headers=pipe.auth)
    assert RID.match(r.headers["x-request-id"])
    assert pipe.ups["patient"].last.headers["x-request-id"] == r.headers["x-request-id"]


async def test_valid_incoming_id_is_propagated_upstream_and_echoed(pipe):
    r = await pipe.client.get("/api/patients", headers={**pipe.auth, "X-Request-ID": "req-from-angular-1"})
    assert r.headers["x-request-id"] == "req-from-angular-1"
    assert pipe.ups["patient"].last.headers["x-request-id"] == "req-from-angular-1"


async def test_invalid_incoming_id_is_replaced(pipe):
    for bad in ("has spaces", "x" * 65, "semi;colon", "new\tline"):
        r = await pipe.client.get("/api/patients", headers={**pipe.auth, "X-Request-ID": bad})
        assert RID.match(r.headers["x-request-id"])
        assert pipe.ups["patient"].last.headers["x-request-id"] == r.headers["x-request-id"]


async def test_gateway_errors_carry_the_same_id_in_header_and_body(pipe):
    for path, status in (("/api/patients", 401), ("/api/internal/x", 404), ("/api/encountersX", 404)):
        r = await pipe.client.get(path)
        assert r.status_code == status
        assert r.json()["error"]["request_id"] == r.headers["x-request-id"]


async def test_a_services_own_request_id_header_is_not_leaked(pipe):
    import httpx

    pipe.ups["patient"]._handler = lambda req: httpx.Response(200, json={}, headers={"X-Request-ID": "svc-side"})
    r = await pipe.client.get("/api/patients", headers=pipe.auth)
    assert r.headers.get_list("x-request-id") == [r.headers["x-request-id"]] and r.headers["x-request-id"] != "svc-side"


async def test_each_request_gets_a_different_id(pipe):
    ids = {(await pipe.client.get("/api/patients", headers=pipe.auth)).headers["x-request-id"] for _ in range(5)}
    assert len(ids) == 5
