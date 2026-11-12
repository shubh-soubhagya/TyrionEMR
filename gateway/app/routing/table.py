"""The route table is code, reviewed like a contract (LLD §6, §18.1). Only URLs and timeouts are configurable."""
from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings

API_PREFIX = "/api"


@dataclass(frozen=True)
class Route:
    prefix: str                 # first segment after /api
    upstream: str               # key in UpstreamRegistry: auth | patient | lab | ai
    timeout_s: float
    max_body_bytes: int
    forward_cookies: bool = False
    pass_set_cookie: bool = False


def build_routes(s: Settings) -> dict[str, Route]:
    d, body = s.upstream_default_timeout_s, s.max_body_bytes
    return {
        "auth":       Route("auth", "auth", d, s.max_auth_body_bytes, forward_cookies=True, pass_set_cookie=True),
        "patients":   Route("patients", "patient", d, body),
        "encounters": Route("encounters", "patient", d, body),
        "labs":       Route("labs", "lab", d, body),
        "ai":         Route("ai", "ai", d, body),
        "insights":   Route("insights", "ai", s.insights_timeout_s, body),
    }


# Exact (method, template). No trailing-slash variants: Angular never sends them.
PUBLIC_ROUTES: frozenset[tuple[str, str]] = frozenset({
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/signup"),
    ("POST", "/api/auth/refresh"),
    ("POST", "/api/auth/logout"),
})
