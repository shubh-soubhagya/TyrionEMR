"""Phase 9 + audit: internal endpoints, bulk status, JSON contracts and the audit trail."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import jsonschema
import pytest
from sqlalchemy import text

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
