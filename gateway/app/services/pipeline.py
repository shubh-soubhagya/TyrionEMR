"""The ordered request pipeline (LLD §5, §25.1). This one method is the only place the order is defined.

Cheap rejections come first, the network call last. Steps are numbered as in the design.
"""
from __future__ import annotations

from starlette.requests import Request
from starlette.responses import Response

from app.core.config import Settings
from app.core.context import client_ip, set_route
from app.core.errors import (
    BadRequest,
    InvalidPath,
    NotFound,
    PayloadTooLarge,
    RateLimited,
    UpstreamNotDeployed,
    UriTooLong,
)
from app.core.security import Claims
from app.routing.paths import UnsafePath, safe_segments
from app.routing.policies import Policy, ip_policies, user_policies
from app.routing.resolver import resolve
from app.routing.table import Route
from app.services.auth_gate import AuthGate
from app.services.proxy import ProxyService
from app.services.rate_limiter import RateLimiter
from app.services.upstreams import UpstreamRegistry

ALLOW = "GET, POST, PUT, PATCH, DELETE, OPTIONS"


class GatewayPipeline:
    def __init__(self, s: Settings, routes: dict[str, Route], registry: UpstreamRegistry,
                 limiter: RateLimiter, auth: AuthGate, proxy: ProxyService) -> None:
        self._s, self._routes, self._reg = s, routes, registry
        self._limiter, self._auth, self._proxy = limiter, auth, proxy

    async def handle(self, request: Request) -> Response:
        scope = request.scope
        raw_path = scope.get("raw_path", b"").decode("latin-1") or scope["path"]
        if len(raw_path) + len(scope.get("query_string", b"")) > self._s.max_url_bytes:    # 1 URL length
            raise UriTooLong()
        if request.method == "OPTIONS":                       # a preflight never gets here (CorsMiddleware)
            return Response(status_code=204, headers={"Allow": ALLOW})
        try:
            segments = safe_segments(raw_path)                                              # 2 path safety
        except UnsafePath:
            raise InvalidPath() from None
        match = resolve(request.method, raw_path, segments, self._routes)                   # 3 resolve
        if match is None:
            raise NotFound()
        set_route(scope, match.template)                                  # route label for log and metrics (D4)
        if not self._reg.configured(match.route.upstream):                                  # 4 deployed?
            request.state.upstream = match.route.upstream
            raise UpstreamNotDeployed(upstream=match.route.upstream)

        ip = client_ip(scope, self._s.trust_proxy_hops)
        for policy in ip_policies(request.method, match.template, self._s):                 # 5 IP limits
            self._enforce(request, policy, ip)

        claims: Claims | None = None
        if not match.public:                                                                # 6 public?
            claims = await self._auth.authenticate(request)                                 # 7 verify JWT
            for policy in user_policies(request.method, match.template, self._s):           # 8 user limits
                self._enforce(request, policy, claims.sub)

        body = await _read_body(request, match.route.max_body_bytes)                        # 9 bounded body
        return await self._proxy.forward(request, match, body, ip)                          # 10 proxy

    def _enforce(self, request: Request, policy: Policy, key: str) -> None:
        decision = self._limiter.check(policy, key)
        if not decision.allowed:
            request.state.rate_limited = True
            raise RateLimited(policy=policy.name, retry_after=decision.retry_after_s)


async def _read_body(request: Request, limit: int) -> bytes:
    if request.method in ("GET", "DELETE") and "content-length" not in request.headers \
            and "transfer-encoding" not in request.headers:
        return b""
    declared = request.headers.get("content-length")
    if declared is not None:
        if not declared.isdigit():
            raise BadRequest("Invalid Content-Length.")
        if int(declared) > limit:                             # refused before a single byte is read
            raise PayloadTooLarge(limit=limit)
    buf = bytearray()
    async for chunk in request.stream():                      # chunked uploads are counted as they arrive
        buf += chunk
        if len(buf) > limit:
            raise PayloadTooLarge(limit=limit)
    return bytes(buf)
