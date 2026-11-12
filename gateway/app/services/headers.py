"""Header policy (LLD §8.3, §8.4, §22): allow-list requests, scrub responses, scope cookies, rewrite Location."""
from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urlsplit

from starlette.datastructures import Headers

from app.routing.table import API_PREFIX

FORWARD_REQUEST_HEADERS = frozenset({
    "accept", "accept-language", "authorization", "cache-control", "content-type",
    "if-match", "if-none-match", "if-modified-since", "idempotency-key", "origin", "user-agent",
})
HOP_BY_HOP = frozenset({
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade",
})
# Date is dropped because Uvicorn adds its own. Content-Length and Content-Type are kept: the body
# bytes are relayed unchanged.
DROP_RESPONSE = HOP_BY_HOP | {"server", "x-powered-by", "x-request-id", "date"}


def upstream_request_headers(incoming: Headers, *, client_ip: str, request_id: str, scheme: str,
                             forward_cookies: bool) -> list[tuple[str, str]]:
    """Allow-list (ADR-G5): anything a client invents (X-User-Id, X-Forwarded-*, Forwarded...) is dropped."""
    out = [(k, v) for k, v in incoming.items() if k in FORWARD_REQUEST_HEADERS]
    if forward_cookies and "cookie" in incoming:
        out.append(("cookie", incoming["cookie"]))
    out += [
        ("x-request-id", request_id),
        ("x-forwarded-for", client_ip),                  # the client IP only, never the client's chain
        ("x-forwarded-proto", scheme),
        ("x-forwarded-host", incoming.get("host", "")),
        ("accept-encoding", "identity"),                 # stream bytes unchanged (ADR-G12)
    ]
    return out


def rewrite_location(value: str, upstream_base: str) -> str:
    """'http://patient-svc:8000/patients/' and '/patients/123' become '/api/...'.
    Foreign absolute URLs are left untouched."""
    parts = urlsplit(value)
    if parts.scheme or parts.netloc:
        base = urlsplit(upstream_base)
        if (parts.scheme, parts.netloc) != (base.scheme, base.netloc):
            return value
        value = parts.path + (f"?{parts.query}" if parts.query else "")
    if value.startswith("/") and not value.startswith(API_PREFIX + "/"):
        return API_PREFIX + value
    return value


def filter_response_headers(items: Iterable[tuple[str, str]], *, pass_set_cookie: bool,
                            upstream_base: str) -> list[tuple[bytes, bytes]]:
    """Returns raw header pairs. A list, not a dict: repeated Set-Cookie headers must survive."""
    items = list(items)
    named_in_connection = {
        t.strip().lower() for k, v in items if k.lower() == "connection" for t in v.split(",")
    }
    out: list[tuple[bytes, bytes]] = []
    for k, v in items:
        lk = k.lower()
        if lk in DROP_RESPONSE or lk in named_in_connection or lk.startswith("proxy-"):
            continue
        if lk == "set-cookie" and not pass_set_cookie:
            continue
        if lk in ("location", "content-location"):
            v = rewrite_location(v, upstream_base)
        out.append((lk.encode("latin-1"), v.encode("latin-1")))
    return out
