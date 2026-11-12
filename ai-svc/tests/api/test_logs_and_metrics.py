"""Observability (LLD B16, A8): logs carry IDs, counts, codes and latencies only; metrics exist and move."""
from __future__ import annotations

import json

import httpx
import pytest

from tests.api.test_summary_api import P1, clock, make_client, run  # noqa: F401
from tests.fixtures import seed

pytestmark = pytest.mark.api


def rendered(capsys) -> str:
    """Everything the service wrote to stdout (the JSON log stream). configure_logging replaces the root handlers,
    so pytest's caplog would see nothing; reading stdout tests what a log collector would actually receive."""
    return capsys.readouterr().out


async def test_no_names_notes_prompts_or_model_text_reach_the_logs(make_client, capsys):  # noqa: F811
    c = await make_client()
    d = await run(c, P1, scenario="tool_roundtrip")
    await c.get("/insights/dashboard")
    await c.get(f"/insights/patients/{P1}/gaps")
    text = rendered(capsys)
    assert d["status"] == "completed"
    spec = next(s for s in seed.SPECS if s.mrn == "PT-000101")
    for secret in (spec.first, spec.last, "Kulkarni", "PT-000101", "PT-000109", "Aditya", spec.dob.isoformat(),
                   "clinical documentation assistant", "PATIENT_RECORD", "Chronic kidney disease",
                   d["ai"]["content"]["history_summary"]["text"], "Bearer ", "gsk_"):
        assert secret not in text, secret


async def test_domain_events_are_logged_with_the_documented_fields(make_client, capsys):  # noqa: F811
    c = await make_client()
    d = await run(c, P1)
    await c.get("/insights/dashboard")
    events = [json.loads(line) for line in rendered(capsys).splitlines() if line.startswith("{")]
    by = {}
    for e in events:
        by.setdefault(e["event"], e)
    started = by["summary.started"]
    assert started["summary_id"] == d["summary_id"] and started["deduplicated"] is False and started["provider"] == "mock"
    fin = by["summary.finished"]
    assert fin["status"] == "completed" and fin["attempts"] == 1 and "refs_total" in fin and "latency_ms" in fin
    assert by["llm.call"]["outcome"] == "ok" and by["llm.call"]["provider"] == "mock"
    snap = by["insights.snapshot"]
    assert snap["patients"] == 10 and snap["need_attention"] == 6
    assert by["http.request"]["route"] and "user_id" in by["http.request"]


async def test_metrics_endpoint_exposes_the_documented_series(make_client):  # noqa: F811
    c = await make_client()
    await run(c, P1)
    await run(c, P1)                                   # cache hit
    await run(c, P1, scenario="invalid_twice", force=True)
    await c.get("/insights/dashboard")
    text = (await httpx.AsyncClient(transport=c._transport, base_url="http://t").get("/metrics")).text
    for series in ("http_request_duration_seconds", "ai_summaries_total", "ai_summary_duration_seconds",
                   "ai_step_duration_seconds", "llm_requests_total", "llm_tokens_total", "llm_slots_in_use",
                   "ai_validation_outcomes_total", "ai_insights_cache_total", "ai_insights_refresh_seconds",
                   "ai_upstream_calls_total", "db_pool_checked_out"):
        assert series in text, series
    assert 'ai_summaries_total{cached="true",error_code="",status="completed"}' in text
    assert 'ai_validation_outcomes_total{outcome="rejected"}' in text
    assert "Kulkarni" not in text and P1 not in text          # no ids or names as metric labels
