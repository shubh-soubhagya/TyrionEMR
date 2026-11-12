import pytest
from starlette.datastructures import Headers

from app.services.headers import filter_response_headers, rewrite_location, upstream_request_headers

BASE = "http://patient-svc:8000"


def req(headers: dict[str, str], **kw):
    defaults = {"client_ip": "172.18.0.1", "request_id": "req-1a2b3c4d5e6f", "scheme": "http",
                "forward_cookies": False}
    return dict(upstream_request_headers(Headers(headers), **{**defaults, **kw}))


# ---- request headers --------------------------------------------------------------------------
def test_allow_listed_headers_are_forwarded_unchanged():
    out = req({"Authorization": "Bearer eyJ.x.y", "Accept": "application/json", "Origin": "http://localhost:4200",
               "Content-Type": "application/json", "If-None-Match": '"abc"', "Idempotency-Key": "k1",
               "User-Agent": "ua", "Accept-Language": "en", "Cache-Control": "no-cache", "If-Match": '"1"',
               "If-Modified-Since": "x"})
    assert out["authorization"] == "Bearer eyJ.x.y"
    assert out["origin"] == "http://localhost:4200"
    assert out["idempotency-key"] == "k1" and out["if-none-match"] == '"abc"'


@pytest.mark.parametrize("spoof", ["X-User-Id", "X-Real-IP", "X-Forwarded-Server", "Forwarded", "X-Role", "Via"])
def test_invented_headers_are_dropped(spoof):
    assert spoof.lower() not in req({spoof: "someone-else"})


def test_client_supplied_forwarding_headers_are_replaced_not_appended():
    out = req({"X-Forwarded-For": "1.2.3.4", "X-Forwarded-Proto": "https", "X-Forwarded-Host": "evil",
               "Host": "localhost:8080"})
    assert out["x-forwarded-for"] == "172.18.0.1"          # client IP only, never the client's chain
    assert out["x-forwarded-proto"] == "http"
    assert out["x-forwarded-host"] == "localhost:8080"


def test_gateway_sets_request_id_and_identity_encoding():
    out = req({"X-Request-ID": "client-chosen"})
    assert out["x-request-id"] == "req-1a2b3c4d5e6f" and out["accept-encoding"] == "identity"


def test_hop_by_hop_and_transfer_encoding_never_forwarded():
    out = req({"Connection": "keep-alive", "Transfer-Encoding": "chunked", "Upgrade": "websocket", "TE": "trailers",
               "Proxy-Authorization": "x", "Keep-Alive": "5"})
    assert not {"connection", "transfer-encoding", "upgrade", "te", "proxy-authorization", "keep-alive"} & set(out)


def test_cookie_forwarded_only_when_the_route_allows_it():
    assert "cookie" not in req({"Cookie": "nephro_rt=abc"})
    assert req({"Cookie": "nephro_rt=abc"}, forward_cookies=True)["cookie"] == "nephro_rt=abc"
    assert "cookie" not in req({}, forward_cookies=True)


def test_authorization_is_byte_for_byte():
    value = "Bearer  eyJ.with.double-space"
    assert req({"Authorization": value})["authorization"] == value


# ---- response headers -------------------------------------------------------------------------
def resp(items, **kw):
    out = filter_response_headers(items, **{"pass_set_cookie": False, "upstream_base": BASE, **kw})
    return [(k.decode(), v.decode()) for k, v in out]


def test_scrubs_hop_by_hop_server_and_request_id():
    out = dict(resp([("Server", "uvicorn"), ("X-Powered-By", "x"), ("X-Request-ID", "svc"), ("Connection", "close"),
                     ("Keep-Alive", "1"), ("Transfer-Encoding", "chunked"), ("Date", "now"),
                     ("Content-Type", "application/json"), ("Content-Length", "2"), ("ETag", '"1"')]))
    assert set(out) == {"content-type", "content-length", "etag"}


def test_headers_named_in_connection_are_dropped():
    out = dict(resp([("Connection", "X-Secret-Hop, close"), ("X-Secret-Hop", "1"), ("X-Keep", "2")]))
    assert out == {"x-keep": "2"}


def test_set_cookie_dropped_unless_route_passes_it():
    items = [("Set-Cookie", "a=1"), ("Content-Type", "application/json")]
    assert dict(resp(items)) == {"content-type": "application/json"}
    assert [v for k, v in resp(items, pass_set_cookie=True) if k == "set-cookie"] == ["a=1"]


def test_repeated_set_cookie_headers_are_never_merged():
    items = [("Set-Cookie", "nephro_rt=; Path=/api/auth; Max-Age=0"), ("Set-Cookie", "other=1; Path=/")]
    cookies = [v for k, v in resp(items, pass_set_cookie=True) if k == "set-cookie"]
    assert cookies == [v for _, v in items]


def test_set_cookie_value_is_not_rewritten():
    cookie = "nephro_rt=abc; Path=/api/auth; HttpOnly; Secure; SameSite=Strict"
    assert ("set-cookie", cookie) in resp([("Set-Cookie", cookie)], pass_set_cookie=True)


# ---- Location rewrite (LLD §22 table) -----------------------------------------------------------
@pytest.mark.parametrize(
    ("upstream", "expected"),
    [
        ("http://patient-svc:8000/patients/", "/api/patients/"),
        ("http://patient-svc:8000/patients?q=1", "/api/patients?q=1"),
        ("/patients/123", "/api/patients/123"),
        ("/labs/patients/x/results?report_id=1", "/api/labs/patients/x/results?report_id=1"),
        ("/api/patients/1", "/api/patients/1"),
        ("https://evil.example/x", "https://evil.example/x"),
        ("http://other-svc:8000/patients", "http://other-svc:8000/patients"),
        ("relative/path", "relative/path"),
    ],
)
def test_location_rewrite(upstream, expected):
    assert rewrite_location(upstream, BASE) == expected


def test_location_and_content_location_are_rewritten_in_responses():
    out = dict(resp([("Location", "/patients/9"), ("Content-Location", "/patients/9")]))
    assert out == {"location": "/api/patients/9", "content-location": "/api/patients/9"}
