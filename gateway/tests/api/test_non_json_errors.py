"""D5: wrapping of non-JSON upstream errors (LLD §23.3 as amended)."""
import httpx
import pytest

PLAIN = {"Content-Type": "text/plain"}


@pytest.mark.parametrize(
    ("status", "code"),
    [(400, "BAD_REQUEST"), (401, "UNAUTHENTICATED"), (403, "FORBIDDEN"), (404, "NOT_FOUND"),
     (405, "METHOD_NOT_ALLOWED"), (413, "PAYLOAD_TOO_LARGE"), (414, "URI_TOO_LONG"), (418, "HTTP_ERROR")],
)
async def test_4xx_keeps_status_and_uses_the_status_map(gw, status, code):
    client, ups = gw
    ups["lab"]._handler = lambda req: httpx.Response(status, content=b"nope", headers=PLAIN)
    r = await client.get("/api/labs/x")
    err = r.json()["error"]
    assert r.status_code == status and err["code"] == code
    assert err["details"] == [{"upstream": "lab"}] and err["request_id"] == r.headers["x-request-id"]
    assert "nope" not in r.text


@pytest.mark.parametrize("status", [500, 501, 502, 503, 504])
async def test_5xx_is_always_upstream_error_with_the_upstream_status(gw, status):
    client, ups = gw
    ups["patient"]._handler = lambda req: httpx.Response(status, content=b"Internal Server Error", headers=PLAIN)
    r = await client.get("/api/patients")
    err = r.json()["error"]
    assert r.status_code == status and err["code"] == "UPSTREAM_ERROR"
    assert err["message"] == "The service returned an unexpected error."
    assert err["details"] == [{"upstream": "patient", "upstream_status": status}]


async def test_html_error_page_is_wrapped_and_never_leaked(gw):
    client, ups = gw
    ups["patient"]._handler = lambda req: httpx.Response(
        500, content=b"<html>Traceback secret</html>", headers={"Content-Type": "text/html"})
    r = await client.get("/api/patients")
    assert r.json()["error"]["code"] == "UPSTREAM_ERROR" and "secret" not in r.text


async def test_internal_error_code_is_reserved_for_gateway_bugs(gw):
    client, ups = gw
    ups["patient"]._handler = lambda req: httpx.Response(500, content=b"x", headers=PLAIN)
    assert (await client.get("/api/patients")).json()["error"]["code"] != "INTERNAL_ERROR"


async def test_json_errors_are_not_wrapped_even_when_5xx(gw):
    client, ups = gw
    body = {"error": {"code": "SERVICE_BUSY", "message": "busy", "details": [], "request_id": "svc"}}
    ups["auth"]._handler = lambda req: httpx.Response(503, json=body, headers={"Retry-After": "1"})
    r = await client.post("/api/auth/login", content=b"{}")
    assert r.status_code == 503 and r.json() == body and r.headers["retry-after"] == "1"


async def test_non_json_success_responses_pass_through(gw):
    client, ups = gw
    ups["lab"]._handler = lambda req: httpx.Response(200, content=b"a,b\n1,2\n", headers={"Content-Type": "text/csv"})
    r = await client.get("/api/labs/export")
    assert r.status_code == 200 and r.content == b"a,b\n1,2\n" and r.headers["content-type"] == "text/csv"
