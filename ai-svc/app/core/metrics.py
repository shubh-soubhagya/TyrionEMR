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


UPSTREAM_CALLS = Counter("ai_upstream_calls_total", "Calls to other services", ["upstream", "outcome"])
INSIGHTS_REFRESH = Histogram("ai_insights_refresh_seconds", "Time to recompute the insights snapshot")
INSIGHTS_CACHE = Counter("ai_insights_cache_total", "Insights snapshot lookups", ["result"])
AI_SUMMARIES = Counter("ai_summaries_total", "Finished summary jobs", ["status", "error_code", "cached"])
AI_SUMMARY_DURATION = Histogram("ai_summary_duration_seconds", "Summary job duration", ["status"],
                                buckets=(0.1, 0.5, 1, 2.5, 5, 10, 20, 40, 90, 120))
AI_STEP_DURATION = Histogram("ai_step_duration_seconds", "Pipeline step duration", ["step"],
                             buckets=(0.005, 0.025, 0.1, 0.5, 1, 2.5, 5, 10, 30, 90))
LLM_REQUESTS = Counter("llm_requests_total", "LLM provider requests", ["provider", "outcome"])
LLM_REQUEST_DURATION = Histogram("llm_request_duration_seconds", "LLM provider request duration", ["provider"])
LLM_TOKENS = Counter("llm_tokens_total", "LLM tokens", ["provider", "direction"])
LLM_BREAKER_OPEN = Gauge("llm_breaker_open", "1 while the circuit breaker is open", ["provider"])
LLM_SLOTS_IN_USE = Gauge("llm_slots_in_use", "LLM concurrency slots in use")
LLM_SLOT_WAIT = Histogram("llm_slot_wait_seconds", "Time waiting for an LLM slot")
LLM_TOOL_CALLS = Counter("llm_tool_calls_total", "Tool calls requested by the model", ["tool", "status"])
AI_VALIDATION = Counter("ai_validation_outcomes_total", "Validation outcomes", ["outcome"])
AI_REAPED = Counter("ai_reaped_jobs_total", "Jobs failed by the reaper")
AI_QUOTA_REJECTIONS = Counter("ai_quota_rejections_total", "Requests refused by the daily quota")
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

