"""Tool calling end to end and the registry on its own (LLD B8, B17.2)."""
from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import text

from app.clients.lab import LabClient
from app.clients.models import Chart, Latest, Trends
from app.clients.patient import PatientClient
from app.context.packet import build_packet
from app.context.refs import RefBuilder
from app.insights.rules.adapters import from_chart
from app.insights.rules.gaps import evaluate
from app.llm.base import ToolCall
from app.orchestrator.facts import build_gaps
from app.orchestrator.orchestrator import JobContext
from app.repositories import summaries as srepo
from app.tools.definitions import Deps
from app.tools.registry import ToolRegistry
from tests.api.test_summary_api import P1, PID, make_client, post, run  # noqa: F401  (fixtures re-used)
from tests.conftest import Upstreams, make_settings
from tests.factories import NOW, TODAY, TZ

pytestmark = pytest.mark.api


# ---- end to end through the mock provider ------------------------------------------------------
async def test_tool_roundtrip_completes_and_records_two_audit_rows(make_client, db_engine):  # noqa: F811
    c = await make_client()
    d = await run(c, scenario="tool_roundtrip")
    assert d["status"] == "completed" and d["validation"]["tool_calls"] == 2
    async with db_engine.connect() as conn:
        rows = (await conn.execute(text("SELECT seq, iteration, tool_name, status, arguments, result_rows, result_bytes"
                                        " FROM llm_tool_calls ORDER BY seq"))).mappings().all()
    assert [r["tool_name"] for r in rows] == ["get_lab_trend", "get_recent_encounters"]
    assert [r["status"] for r in rows] == ["ok", "ok"] and rows[0]["arguments"] == {"test_code": "EGFR"}
    assert rows[0]["result_rows"] == 8 and rows[0]["result_bytes"] > 0
    ctx = (await c.get(f"/ai/summaries/{d['summary_id']}?include=context")).json()["context"]
    assert [t["tool"] for t in ctx["tool_results"]] == ["get_lab_trend", "get_recent_encounters"]
    assert all("value" not in json.dumps(t) for t in ctx["tool_results"])          # sizes only, never results
    assert d["validation"]["attempts"] == 2


async def test_tools_disabled_runs_single_shot(make_client, db_engine):  # noqa: F811
    c = await make_client(llm_tools_enabled=False)
    d = await run(c, scenario="tool_roundtrip")
    assert d["status"] == "completed" and d["validation"]["tool_calls"] == 0 and d["validation"]["attempts"] == 1
    async with db_engine.connect() as conn:
        assert (await conn.execute(text("SELECT count(*) FROM llm_tool_calls"))).scalar() == 0


async def test_tool_flag_is_part_of_the_cache_key(make_client):  # noqa: F811
    on = await make_client()
    first = await run(on)
    off = await make_client(llm_tools_enabled=False)
    second = await run(off)
    assert second["cached"] is False and second["summary_id"] != first["summary_id"]


async def test_a_failing_tool_is_fed_back_as_an_error_not_a_failed_job(make_client, upstreams: Upstreams,  # noqa: F811
                                                                        db_engine):
    c = await make_client()
    upstreams.fail["/encounters"] = 503                 # only the tool call hits this path; the baseline reads do not
    d = await run(c, scenario="tool_roundtrip")
    assert d["status"] == "completed" and d["validation"]["tool_calls"] == 2
    async with db_engine.connect() as conn:
        rows = (await conn.execute(text("SELECT tool_name, status, error_code FROM llm_tool_calls ORDER BY seq"))).all()
    assert [tuple(r) for r in rows] == [("get_lab_trend", "ok", None),
                                        ("get_recent_encounters", "error", "UPSTREAM_UNAVAILABLE")]


# ---- the registry on its own -------------------------------------------------------------------
@pytest.fixture
async def rig(upstreams: Upstreams, db_engine):
    from app.db.session import create_engine, create_sessionmaker
    settings = make_settings()
    engine = create_engine(settings)
    sm = create_sessionmaker(engine)
    patients, labs = PatientClient(settings), LabClient(settings)
    registry = ToolRegistry(settings, sm, Deps(patients, labs))
    p = next(x for x in upstreams.patients if x["mrn"] == "PT-000101")
    chart, latest, trends = Chart.model_validate(p["chart"]), Latest.model_validate(p["latest"]), Trends.model_validate(
        p["trends"])
    findings = evaluate(from_chart(chart, latest, trends, today=TODAY), today=TODAY, now=NOW, tz=TZ)
    builder = RefBuilder(TZ)
    packet = build_packet(chart, latest, trends, findings, today=TODAY, builder=builder)
    gaps = build_gaps(findings, chart, builder)
    async with sm() as s, s.begin():
        row = await srepo.insert_running(s, patient_id=p["id"], requested_by=uuid.uuid4(), request_id=None,
                                         force=False, provider="mock", model="m", prompt_version="v1",
                                         schema_version="out-1", rules_version="r", tools_enabled=True)
    job = JobContext(row["id"], p["id"], row["requested_by"], "Bearer t", "req-1")
    job.refs, job.gaps = builder, gaps

    class Rig:
        pass

    r = Rig()
    r.registry, r.job, r.packet, r.builder, r.sm, r.settings = registry, job, packet, builder, sm, settings
    yield r
    await patients.aclose()
    await labs.aclose()
    await engine.dispose()


async def call(rig, name, args, iteration=1):
    return await rig.registry.execute(ToolCall(f"c{rig.job.tool_calls}", name, args), rig.job, iteration)


async def test_definitions_have_schemas_and_never_expose_patient_id(rig):
    defs = {d.name: d for d in rig.registry.definitions()}
    assert set(defs) == {"get_conditions", "get_medications_and_allergies", "get_recent_encounters", "get_lab_history",
                         "get_lab_trend", "get_gap_report"}
    for d in defs.values():
        assert "patient_id" not in json.dumps(d.parameters) and d.parameters.get("additionalProperties") is False
    assert defs["get_lab_trend"].parameters["properties"]["test_code"]["enum"] == [
        "CREAT", "EGFR", "BUN", "K", "HB", "CA", "PHOS", "UACR"]
    assert "from" in defs["get_lab_history"].parameters["properties"]


async def test_patient_id_cannot_be_smuggled_in_as_an_argument(rig):
    res = await call(rig, "get_lab_trend", {"test_code": "EGFR", "patient_id": str(uuid.uuid4())})
    assert not res.ok and "patient_id" in res.data["error"]
    res = await call(rig, "get_conditions", {"patient_id": str(uuid.uuid4())})
    assert not res.ok


async def test_unknown_tool_is_rejected_and_stored_as_unknown(rig):
    res = await call(rig, "delete_patient", {})
    assert not res.ok and "Available:" in res.data["error"]
    async with rig.sm() as s:
        rows = (await s.execute(text("SELECT tool_name, status, arguments FROM llm_tool_calls"))).mappings().all()
    assert rows[0]["tool_name"] == "unknown" and rows[0]["status"] == "rejected"
    assert rows[0]["arguments"] == {"_name": "delete_patient"}


async def test_invalid_arguments_are_rejected_with_a_short_message(rig):
    for name, args in (("get_lab_trend", {"test_code": "XYZ"}), ("get_recent_encounters", {"limit": 99}),
                       ("get_recent_encounters", {"limit": 2, "bogus": 1}), ("get_lab_history", {})):
        res = await call(rig, name, args)
        assert not res.ok and len(res.data["error"]) < 300


async def test_lab_trend_reuses_the_packets_refs(rig):
    res = await call(rig, "get_lab_trend", {"test_code": "EGFR"})
    assert res.ok and res.data["trend"]["ref"] == "trend:EGFR" and len(res.data["points"]) == 8
    last = res.data["points"][-1]
    packet_egfr = next(x for x in rig.packet["labs"]["latest"] if x["test"] == "EGFR")
    assert last["ref"] == packet_egfr["ref"]                       # the same result keeps the same ref
    assert all(p["ref"] in rig.builder.index for p in res.data["points"])


async def test_lab_history_filters_superseded_and_gives_refs(rig):
    res = await call(rig, "get_lab_history", {"test_code": "CREAT", "from": "2025-01-01"})
    assert res.ok and res.data["items"] and res.data["truncated"] is False
    assert all(i["ref"].startswith("lab:CREAT:") for i in res.data["items"])


async def test_encounters_respect_include_notes_and_reuse_enc_refs(rig):
    full = await call(rig, "get_recent_encounters", {"limit": 3})
    brief = await call(rig, "get_recent_encounters", {"limit": 3, "include_notes": False})
    assert full.data["items"][0]["ref"] == "enc:1" and "assessment" in full.data["items"][0]
    assert "assessment" not in brief.data["items"][0] and brief.data["items"][0]["ref"] == "enc:1"


async def test_conditions_medications_and_gap_report(rig):
    cond = await call(rig, "get_conditions", {"status": "active"})
    assert cond.data["items"][0]["ref"] == "cond:1"
    meds = await call(rig, "get_medications_and_allergies", {})
    assert [m["ref"] for m in meds.data["medications"]] == ["med:1", "med:2"] and meds.data["allergies"] == []
    gaps = await call(rig, "get_gap_report", {})
    assert gaps.ok and gaps.data["items"] == []                          # PT-000101 has no findings


async def test_results_are_capped_and_marked_truncated(rig, monkeypatch):
    big = {"items": [{"id": str(uuid.uuid4()), "test_code": "CREAT", "collected_at": f"2026-01-{i % 28 + 1:02d}T00:00:00+00:00",
                      "value": 1.0 + i, "unit": "mg/dL", "flag": "normal", "ref_low": None, "ref_high": None,
                      "superseded": False} for i in range(120)], "total": 120}

    async def fake(*a, **k):
        return big

    monkeypatch.setattr(rig.registry._deps.labs, "results", fake)
    res = await call(rig, "get_lab_history", {"test_code": "CREAT"})
    assert res.data["truncated"] is True and len(res.data["items"]) <= 50
    assert len(res.to_message().encode()) <= rig.settings.tool_result_max_bytes


async def test_upstream_failure_and_timeout_become_tool_errors(rig, upstreams, monkeypatch):
    upstreams.fail["/internal/patients"] = 503
    res = await call(rig, "get_conditions", {})
    assert not res.ok and res.data == {"error": "Data could not be retrieved."}
    upstreams.fail.clear()
    import asyncio

    async def slow(*a, **k):
        await asyncio.sleep(5)

    monkeypatch.setattr(rig.registry._deps.patients, "tool", slow)
    rig.registry._cfg = make_settings(tool_timeout_s=0.05)
    res = await call(rig, "get_conditions", {})
    assert not res.ok
    async with rig.sm() as s:
        codes = [r[0] for r in (await s.execute(text("SELECT error_code FROM llm_tool_calls ORDER BY seq"))).all()]
    assert codes == ["UPSTREAM_UNAVAILABLE", "TOOL_TIMEOUT"]


async def test_the_job_budget_is_enforced(rig):
    for _ in range(rig.settings.llm_max_tool_calls):
        assert (await call(rig, "get_gap_report", {})).ok
    res = await call(rig, "get_gap_report", {})
    assert not res.ok and "budget" in res.data["error"]


async def test_tool_calls_are_audited_in_order_with_iteration(rig):
    await call(rig, "get_gap_report", {}, iteration=1)
    await call(rig, "get_conditions", {}, iteration=2)
    async with rig.sm() as s:
        rows = (await s.execute(text("SELECT seq, iteration, tool_name FROM llm_tool_calls ORDER BY seq"))).all()
    assert [tuple(r) for r in rows] == [(1, 1, "get_gap_report"), (2, 2, "get_conditions")]
