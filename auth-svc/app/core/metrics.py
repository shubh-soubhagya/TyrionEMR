"""Prometheus metrics. Metric objects are module singletons (registered once per process)."""
from __future__ import annotations

import time

from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, Histogram, generate_latest
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.context import route_template

HTTP_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration",
    ["route", "method", "status"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)


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

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            route = route_template(scope)
            if route != "/metrics":
                HTTP_DURATION.labels(route, scope["method"], str(status)).observe(time.perf_counter() - start)


def mount_metrics(app: FastAPI) -> None:
    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ---- auth business metrics (LLD §24.2) ----
from prometheus_client import Counter, Gauge  # noqa: E402

AUTH_LOGIN = Counter("auth_login_total", "Login attempts", ["outcome"])
AUTH_SIGNUP = Counter("auth_signup_total", "Signup attempts", ["outcome"])
AUTH_REFRESH = Counter("auth_refresh_total", "Refresh attempts", ["outcome"])
AUTH_REUSE = Counter("auth_refresh_reuse_detected_total", "Refresh token reuse detections")
ARGON2_SECONDS = Histogram("auth_argon2_seconds", "Argon2 duration", ["op"],
                           buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5))
ARGON2_INFLIGHT = Gauge("auth_argon2_inflight", "Concurrent argon2 operations")
