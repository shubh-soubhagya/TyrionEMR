"""Prometheus metrics. Metric objects are module singletons (registered once per process)."""
from __future__ import annotations

import time

from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.context import route_template

HTTP_REQUESTS = Counter("http_requests_total", "HTTP requests", ["route", "method", "status"])
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
                HTTP_REQUESTS.labels(route, scope["method"], str(status)).inc()
                HTTP_DURATION.labels(route, scope["method"], str(status)).observe(time.perf_counter() - start)


# domain metrics (LLD B12). Labels are codes and flags only, never values.
RESULTS_CREATED = Counter("lab_results_created_total", "Results stored (originals and corrections)",
                          ["test_code", "flag"])
CORRECTIONS = Counter("lab_corrections_total", "Result corrections appended", ["test_code"])
STATUS_RECOMPUTE = Histogram("lab_status_recompute_seconds", "Time to recompute patient_lab_status")
PATIENT_CLIENT_REQUESTS = Counter("lab_patient_client_requests_total", "Calls to patient-svc by outcome", ["outcome"])
ADVISORY_LOCK_WAIT = Histogram("lab_advisory_lock_wait_seconds", "Time waiting for the per-patient advisory lock",
                               buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1, 2))
CATALOG_RELOADS = Counter("lab_catalog_reload_total", "Catalog cache reloads", ["result"])
DB_POOL_CHECKED_OUT = Gauge("db_pool_checked_out", "Connections currently checked out of the pool")
DB_TRIGGER_REJECTIONS = Counter("db_trigger_rejections_total",
                                "Writes rejected by a database trigger (a service bug: should stay 0)", ["hint"])


def mount_metrics(app: FastAPI) -> None:
    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        engine = getattr(app.state, "engine", None)
        if engine is not None:
            DB_POOL_CHECKED_OUT.set(engine.pool.checkedout())     # sampled at scrape time
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

