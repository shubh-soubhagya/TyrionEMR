"""Prometheus metrics. Metric objects are module singletons (registered once per process).

Same histogram name and buckets as the services so one dashboard reads every component. Gateway-specific
metrics (LLD §30.2) are added in Phase 7.
"""
from __future__ import annotations

import hmac
import time

from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.context import get_route, set_route
from app.core.errors import Forbidden

HTTP_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration",
    ["route", "method", "status"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)

RATE_LIMITED = Counter("gateway_rate_limited_total", "Requests rejected by a rate-limit policy", ["policy"])

JWKS_REFRESH = Counter("gateway_jwks_refresh_total", "JWKS fetch attempts", ["outcome"])
JWKS_KEYS = Gauge("gateway_jwks_keys", "Public keys in the current JWKS")
AUTH_FAILURES = Counter("gateway_auth_failures_total", "Rejected access tokens", ["reason"])

UPSTREAM_DURATION = Histogram("gateway_upstream_duration_seconds", "Time to upstream response headers", ["upstream"],
                              buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10))
UPSTREAM_ERRORS = Counter("gateway_upstream_errors_total", "Transport failures talking to an upstream",
                          ["upstream", "kind"])

UPSTREAM_UP = Gauge("gateway_upstream_up", "1 when the last /health probe of the upstream succeeded", ["upstream"])
INFLIGHT = Gauge("gateway_inflight_requests", "Requests currently being handled")

# Gateway-owned probes stay out of the histogram (they still get access-log lines, D4).
EXCLUDED_ROUTES = frozenset({"/health", "/ready", "/metrics"})


class MetricsMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        start = time.perf_counter()
        status = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        INFLIGHT.inc()
        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            INFLIGHT.dec()
            route = get_route(scope)
            if route not in EXCLUDED_ROUTES:
                HTTP_DURATION.labels(route, scope["method"], str(status)).observe(time.perf_counter() - start)


def mount_metrics(app: FastAPI, token: str) -> None:
    """GET /metrics (LLD §27.3). With METRICS_TOKEN set it needs ``Authorization: Bearer <token>``;
    the caller does not mount it at all when METRICS_ENABLED=false (then it is an ordinary 404)."""

    @app.get("/metrics", include_in_schema=False)
    async def metrics(request: Request) -> Response:
        set_route(request.scope, "/metrics")
        if token:
            scheme, _, supplied = request.headers.get("authorization", "").partition(" ")
            # constant-time comparison: the token is a shared secret
            if scheme.lower() != "bearer" or not hmac.compare_digest(supplied.strip().encode(), token.encode()):
                raise Forbidden()
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
