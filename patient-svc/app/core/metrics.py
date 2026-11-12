"""Prometheus metrics. Metric objects are module singletons (registered once per process)."""
from __future__ import annotations

import time

from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
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


DB_POOL_CHECKED_OUT = Gauge("db_pool_checked_out", "Connections currently checked out of the pool")
ENCOUNTERS_FINALIZED = Counter("encounters_finalized_total", "Encounters finalized")
PROBLEM_LIST_CHANGES = Counter("problem_list_changes_total", "Problem-list changes made by finalize", ["kind"])
OPTIMISTIC_CONFLICTS = Counter("optimistic_conflicts_total", "Version conflicts returned", ["resource"])
DB_TRIGGER_REJECTIONS = Counter("db_trigger_rejections_total",
                                "Writes rejected by a database trigger (a service bug: should stay 0)", ["hint"])


def mount_metrics(app: FastAPI) -> None:
    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        engine = getattr(app.state, "engine", None)
        if engine is not None:
            DB_POOL_CHECKED_OUT.set(engine.pool.checkedout())     # sampled at scrape time
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

