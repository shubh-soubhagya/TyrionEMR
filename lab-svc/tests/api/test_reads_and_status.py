"""Phases 7-9: read model, results/trends/latest/summary, internal endpoints, audit, contracts."""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import jsonschema
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

pytestmark = pytest.mark.api
BASE = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
CONTRACTS = Path(__file__).resolve().parents[2] / "contracts" / "lab"


def stamp(days: int) -> str:
    return (BASE + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


async def add(api: httpx.AsyncClient, pid, day: int, **vals: float) -> dict:
    units = {"CREAT": "mg/dL", "EGFR": "mL/min/1.73m²", "K": "mmol/L", "UACR": "mg/g", "HB": "g/dL"}
    resp = await api.post(f"/labs/patients/{pid}/reports", json={
        "collected_at": stamp(day), "results": [{"test_code": k, "value": v, "unit": units[k]} for k, v in vals.items()]})
    assert resp.status_code == 201, resp.text
    return resp.json()


async def decline(api: httpx.AsyncClient, patients, sex: str = "M"):
    """Five eGFR/creatinine points over 120 days: a rapid decline."""
    pid = patients.add(sex)
    for i, (e, c) in enumerate([(60, 1.3), (56, 1.5), (52, 1.7), (48, 1.9), (44, 2.1)]):
        await add(api, pid, i * 30, EGFR=e, CREAT=c)
    return pid


# ---- read model ----------------------------------------------------------------------------------------
async def test_latest_reports_category_and_rapid_decline(api, patients) -> None:
    pid = await decline(api, patients)
    body = (await api.get(f"/labs/patients/{pid}/latest")).json()
    assert body["egfr_category"] == {"code": "G3b", "label": "Moderately to severely decreased"}
    assert body["rapid_decline"] is True and body["has_critical"] is False
    assert body["latest"]["EGFR"]["value"] == 44 and body["latest"]["CREAT"]["flag"] == "high"
    assert body["uacr_category"] is None


async def test_latest_for_patient_without_labs_is_empty_not_guessed(api) -> None:
    body = (await api.get(f"/labs/patients/{uuid.uuid4()}/latest")).json()
    assert body["latest"] == {} and body["egfr_category"] is None and body["last_result_at"] is None


async def test_critical_only_counts_the_latest_result_per_test(api, patients) -> None:
    pid = patients.add()
    await add(api, pid, 0, K=6.8)
    assert (await api.get(f"/labs/patients/{pid}/latest")).json()["has_critical"] is True
    await add(api, pid, 10, K=4.4)
    assert (await api.get(f"/labs/patients/{pid}/latest")).json()["has_critical"] is False


async def test_correction_updates_the_read_model(api, patients) -> None:
    pid = patients.add()
    res = (await add(api, pid, 0, K=6.8))["results"][0]
    await api.post(f"/labs/results/{res['id']}/correct", json={"value": 4.2, "unit": "mmol/L", "reason": "re-checked against report"})
    body = (await api.get(f"/labs/patients/{pid}/latest")).json()
    assert body["latest"]["K"]["value"] == 4.2 and body["has_critical"] is False


async def test_uacr_category(api, patients) -> None:
    pid = patients.add()
    await add(api, pid, 0, UACR=450)
    assert (await api.get(f"/labs/patients/{pid}/latest")).json()["uacr_category"]["code"] == "A3"


async def test_failed_write_leaves_the_read_model_untouched(api, patients, db_engine) -> None:
    pid = patients.add()
    await add(api, pid, 0, K=4.0)
    bad = await api.post(f"/labs/patients/{pid}/reports", json={"collected_at": stamp(5), "results": [
        {"test_code": "K", "value": 9, "unit": "mmol/L"}, {"test_code": "CREAT", "value": 1, "unit": "bad"}]})
    assert bad.status_code == 422
    async with db_engine.connect() as c:
        row = (await c.execute(text("SELECT latest FROM patient_lab_status WHERE patient_id = :p"), {"p": pid})).scalar_one()
    assert row["K"]["value"] == 4.0


async def test_rebuild_equals_incremental_state(api, patients, db_engine) -> None:
    from app.cli.rebuild_status import rebuild
    pid = await decline(api, patients)
    q = text("SELECT latest, egfr_category, uacr_category, egfr_stats, creat_stats, egfr_spark, has_critical, "
             "rapid_decline, last_result_at FROM patient_lab_status WHERE patient_id = :p")
    async with db_engine.connect() as c:
        before = (await c.execute(q, {"p": pid})).one()
        await c.execute(text("TRUNCATE patient_lab_status"))
        await c.commit()
    assert await rebuild(async_sessionmaker(db_engine)) == 1
    async with db_engine.connect() as c:
        assert (await c.execute(q, {"p": pid})).one() == before


async def test_spark_keeps_only_the_last_twelve_points(api, patients) -> None:
    pid = patients.add()
    for i in range(15):
        await add(api, pid, i * 7, EGFR=70 - i)
    sp = (await api.get("/labs/summary", params={"patient_ids": str(pid)})).json()["items"][0]["egfr_spark"]
    assert len(sp) == 12 and sp[-1]["v"] == 56 and sp[0]["v"] == 67


# ---- results -------------------------------------------------------------------------------------------
async def test_results_filters_and_paging(api, patients) -> None:
    pid = patients.add("M")
    await add(api, pid, 0, K=4.0, CREAT=1.0)
    await add(api, pid, 30, K=5.6, CREAT=1.1)
    await add(api, pid, 60, K=4.1, CREAT=1.6)
    get = lambda **p: api.get(f"/labs/patients/{pid}/results", params=p)    # noqa: E731
    assert (await get()).json()["total"] == 6
    ab = (await get(flag="abnormal")).json()
    assert ab["total"] == 2 and {x["flag"] for x in ab["items"]} == {"high"}
    assert (await get(test="K")).json()["total"] == 3
    win = (await get(**{"from": stamp(20), "to": stamp(40)})).json()
    assert win["total"] == 2 and {x["collected_at"][:10] for x in win["items"]} == {stamp(30)[:10]}
    p1 = (await get(size=4, page=1)).json()
    p2 = (await get(size=4, page=2)).json()
    assert len(p1["items"]) == 4 and len(p2["items"]) == 2 and p1["total"] == 6
    assert p1["items"][0]["collected_at"] >= p1["items"][-1]["collected_at"]          # newest first
    assert (await get(flag="critical_high")).json()["total"] == 0


async def test_results_validation(api, patients) -> None:
    pid = patients.add()
    assert (await api.get(f"/labs/patients/{pid}/results", params={"flag": "scary"})).status_code == 422
    assert (await api.get(f"/labs/patients/{pid}/results", params={"test": "NOPE"})).status_code == 422
    assert (await api.get(f"/labs/patients/{pid}/results", params={"size": 500})).status_code == 422
    assert (await api.get(f"/labs/patients/{pid}/results", params={"page": 0})).status_code == 422


# ---- trends --------------------------------------------------------------------------------------------
async def test_trends_series_and_stats(api, patients) -> None:
    pid = await decline(api, patients)
    body = (await api.get(f"/labs/patients/{pid}/trends", params={"tests": "CREAT,EGFR"})).json()
    assert [s["test_code"] for s in body["series"]] == ["CREAT", "EGFR"]
    egfr = body["series"][1]
    assert egfr["unit"] == "mL/min/1.73m²" and [p["value"] for p in egfr["points"]] == [60, 56, 52, 48, 44]
    assert egfr["stats"]["direction"] == "worsening" and egfr["stats"]["rapid_decline"] is True
    assert egfr["points"][0]["ref_low"] == 90
    assert body["series"][0]["stats"]["direction"] == "worsening"


async def test_trend_stats_describe_the_selected_window(api, patients) -> None:
    pid = await decline(api, patients)
    body = (await api.get(f"/labs/patients/{pid}/trends", params={"tests": "EGFR", "from": stamp(55)})).json()
    s = body["series"][0]
    assert s["stats"]["n"] == 3 and s["stats"]["first"] == 52          # recomputed for the window, not all-time


async def test_two_points_are_insufficient_data(api, patients) -> None:
    pid = patients.add()
    await add(api, pid, 0, EGFR=60)
    await add(api, pid, 30, EGFR=40)
    s = (await api.get(f"/labs/patients/{pid}/trends", params={"tests": "EGFR"})).json()["series"][0]
    assert s["stats"]["direction"] == "insufficient_data" and s["stats"]["slope_per_year"] is None


async def test_trends_empty_and_unknown(api, patients) -> None:
    s = (await api.get(f"/labs/patients/{uuid.uuid4()}/trends", params={"tests": "EGFR"})).json()["series"][0]
    assert s["points"] == [] and s["stats"] is None
    assert (await api.get(f"/labs/patients/{uuid.uuid4()}/trends", params={"tests": "NOPE"})).status_code == 422


# ---- summary -------------------------------------------------------------------------------------------
async def test_summary_batch_returns_every_requested_id(api, patients) -> None:
    sick, none = await decline(api, patients), uuid.uuid4()
    body = (await api.get("/labs/summary", params={"patient_ids": f"{sick},{none},{sick}"})).json()
    assert [i["patient_id"] for i in body["items"]] == [str(sick), str(none)]          # de-duplicated, order kept
    a, b = body["items"]
    assert a["has_data"] and a["egfr_category"] == "G3b" and a["rapid_decline"] and a["latest_egfr"]["value"] == 44
    assert len(a["egfr_spark"]) == 5
    assert b == {"patient_id": str(none), "has_data": False, "latest_egfr": None, "egfr_category": None,
                 "egfr_spark": [], "has_critical": False, "rapid_decline": False, "last_result_at": None}


async def test_summary_limits_and_validation(api) -> None:
    ids = ",".join(str(uuid.uuid4()) for _ in range(51))
    assert (await api.get("/labs/summary", params={"patient_ids": ids})).status_code == 422
    assert (await api.get("/labs/summary", params={"patient_ids": ",".join(str(uuid.uuid4()) for _ in range(50))})
            ).status_code == 200
    assert (await api.get("/labs/summary", params={"patient_ids": "not-a-uuid"})).status_code == 422
    assert (await api.get("/labs/summary", params={"patient_ids": ""})).status_code == 422
    assert (await api.get("/labs/summary")).status_code == 422


# ---- internal ------------------------------------------------------------------------------------------
async def test_internal_twins_match_public(api, patients) -> None:
    pid = await decline(api, patients)
    for path in ("results", "trends", "latest"):
        pub = (await api.get(f"/labs/patients/{pid}/{path}")).json()
        internal = (await api.get(f"/internal/labs/patients/{pid}/{path}")).json()
        assert pub == internal


async def test_internal_requires_a_token(client) -> None:
    assert (await client.get("/internal/labs/status")).status_code == 401


async def test_bulk_status_pages_cover_every_patient_exactly_once(api, patients) -> None:
    ids = set()
    for _ in range(5):
        pid = patients.add()
        await add(api, pid, 0, K=4.0)
        ids.add(str(pid))
    seen, cursor = [], None
    for _ in range(10):
        page = (await api.get("/internal/labs/status", params={"limit": 2, **({"cursor": cursor} if cursor else {})})).json()
        seen += [i["patient_id"] for i in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert sorted(seen) == sorted(ids) and len(seen) == len(set(seen))


async def test_bulk_limit_is_capped(api) -> None:
    assert (await api.get("/internal/labs/status", params={"limit": 5000})).status_code == 422


# ---- contracts -----------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["latest", "results", "trends", "summary", "status", "report"])
async def test_responses_match_json_schema_contracts(api, patients, name) -> None:
    pid = await decline(api, patients)
    urls = {
        "latest": f"/internal/labs/patients/{pid}/latest",
        "results": f"/internal/labs/patients/{pid}/results",
        "trends": f"/internal/labs/patients/{pid}/trends",
        "summary": f"/labs/summary?patient_ids={pid}",
        "status": "/internal/labs/status",
    }
    if name == "report":
        data = await add(api, patients.add(), 0, K=4.0, CREAT=1.0)
    else:
        data = (await api.get(urls[name])).json()
    schema = json.loads((CONTRACTS / f"{name}.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(data, schema)


# ---- audit ---------------------------------------------------------------------------------------------
async def test_every_write_and_read_is_audited_without_values(api, patients, db_engine) -> None:
    pid = patients.add()
    res = (await add(api, pid, 0, K=6.8))["results"][0]
    await api.post(f"/labs/results/{res['id']}/correct", json={"value": 4.2, "unit": "mmol/L", "reason": "re-checked against report"})
    await api.get(f"/labs/patients/{pid}/results")
    await api.get(f"/labs/patients/{pid}/trends")
    await api.get(f"/labs/patients/{pid}/latest")
    await api.get("/labs/summary", params={"patient_ids": str(pid)})
    await api.get("/internal/labs/status")
    async with db_engine.connect() as c:
        rows = (await c.execute(text("SELECT action, details::text FROM audit_events ORDER BY id"))).all()
    assert [a for a, _ in rows] == ["lab.report.create", "lab.result.correct", "lab.results.view", "lab.trends.view",
                                    "lab.latest.view", "lab.summary.view", "lab.status.bulk_export"]
    blob = " ".join(d for _, d in rows)
    assert "6.8" not in blob and "4.2" not in blob


async def test_failed_write_leaves_no_audit_row(api, patients, db_engine) -> None:
    await api.post(f"/labs/patients/{patients.add()}/reports",
                   json={"collected_at": stamp(0), "results": [{"test_code": "K", "value": 1, "unit": "x"}]})
    async with db_engine.connect() as c:
        assert (await c.execute(text("SELECT count(*) FROM audit_events"))).scalar_one() == 0


async def test_audit_rows_are_append_only(api, patients, db_engine) -> None:
    await add(api, patients.add(), 0, K=4.0)
    async with db_engine.connect() as c:
        with pytest.raises(Exception, match="append-only"):
            await c.execute(text("DELETE FROM audit_events"))
