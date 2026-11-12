"""Phase 9 + audit: internal endpoints, bulk status, JSON contracts and the audit trail."""
from __future__ import annotations

import json
import uuid
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
async def test_internal_trends_and_latest_are_the_public_contracts(api, patients) -> None:
    pid = await decline(api, patients)
    for path in ("trends", "latest"):
        assert (await api.get(f"/labs/patients/{pid}/{path}")).json() == (
            await api.get(f"/internal/labs/patients/{pid}/{path}")).json()


async def test_internal_results_use_limit_and_say_when_the_cap_cut_rows(api, patients) -> None:
    pid = await decline(api, patients)                                     # 10 current results
    cut = (await api.get(f"/internal/labs/patients/{pid}/results", params={"limit": 4})).json()
    assert len(cut["items"]) == 4 and cut["total"] == 10 and cut["truncated"] is True
    full = (await api.get(f"/internal/labs/patients/{pid}/results", params={"limit": 50})).json()
    assert len(full["items"]) == 10 and full["truncated"] is False
    default = (await api.get(f"/internal/labs/patients/{pid}/results")).json()
    assert default["size"] == 50
    pub = (await api.get(f"/labs/patients/{pid}/results", params={"size": 100})).json()
    assert [i["id"] for i in pub["items"]] == [i["id"] for i in full["items"]]      # same data, same order


async def test_internal_results_cap_and_filters(api, patients) -> None:
    pid = await decline(api, patients)
    url = f"/internal/labs/patients/{pid}/results"
    assert (await api.get(url, params={"limit": 51})).status_code == 422
    assert (await api.get(url, params={"limit": 0})).status_code == 422
    only = (await api.get(url, params={"test": "EGFR"})).json()
    assert only["total"] == 5 and {i["test_code"] for i in only["items"]} == {"EGFR"}


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


async def test_bulk_limit_is_capped_at_200_and_a_bad_cursor_is_400(api) -> None:
    assert (await api.get("/internal/labs/status", params={"limit": 201})).status_code == 422
    assert (await api.get("/internal/labs/status", params={"limit": 200})).status_code == 200
    bad = await api.get("/internal/labs/status", params={"cursor": "not-a-uuid"})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "INVALID_CURSOR"


async def test_bulk_status_item_shape_has_no_sparkline_and_a_count(api, patients) -> None:
    pid = await decline(api, patients)
    item = next(i for i in (await api.get("/internal/labs/status")).json()["items"] if i["patient_id"] == str(pid))
    assert item["result_count"] == 10 and "egfr_spark" not in item and item["rapid_decline"] is True
    assert item["egfr_stats"]["direction"] == "worsening" and item["latest"]["EGFR"]["value"] == 44


async def test_status_pages_are_in_patient_id_order(api, patients) -> None:
    for _ in range(4):
        await add(api, patients.add(), 0, K=4.0)
    ids = [i["patient_id"] for i in (await api.get("/internal/labs/status")).json()["items"]]
    assert ids == sorted(ids)


# ---- contracts -----------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["latest", "results", "results-internal", "trends", "summary", "status", "report",
                                  "correction"])
async def test_responses_match_json_schema_contracts(api, patients, name) -> None:
    pid = await decline(api, patients)
    urls = {
        "latest": f"/internal/labs/patients/{pid}/latest",
        "results": f"/labs/patients/{pid}/results",
        "results-internal": f"/internal/labs/patients/{pid}/results",
        "trends": f"/internal/labs/patients/{pid}/trends",
        "summary": f"/labs/summary?patient_ids={pid}",
        "status": "/internal/labs/status",
    }
    if name == "report":
        data = await add(api, patients.add(), 0, K=4.0, CREAT=1.0)
    elif name == "correction":
        res = (await add(api, patients.add(), 0, K=6.5))["results"][0]
        data = (await api.post(f"/labs/results/{res['id']}/correct",
                               json={"value": 4.0, "unit": "mmol/L", "reason": "re-keyed"})).json()
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


def test_patient_basic_contract_is_what_the_client_consumes() -> None:
    """Consumer side of GET /internal/patients/{id}/basic (LLD B13.4); patient-svc tests the provider side against
    the same schema file."""
    import asyncio

    from app.services.patient_client import PatientClient
    from tests.conftest import make_settings

    schema_path = Path(__file__).resolve().parents[3] / "patient-svc" / "contracts" / "patient" / "basic.schema.json"
    if not schema_path.exists():
        pytest.skip("patient-svc contract not present in this checkout")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    body = {"id": str(uuid.uuid4()), "sex": "F", "date_of_birth": "1980-02-29"}
    jsonschema.validate(body, schema)                                          # the stub we test against is valid
    assert set(schema["required"]) >= {"sex", "date_of_birth"}                 # everything the client reads is promised
    got = asyncio.run(PatientClient(make_settings(), httpx.MockTransport(
        lambda _: httpx.Response(200, json=body))).basic(uuid.UUID(body["id"]), "Bearer x", None))
    assert (got.sex, str(got.date_of_birth)) == ("F", "1980-02-29")
    for extra in ({"sex": "X", "date_of_birth": "1980-01-01", "id": body["id"]},):
        assert not jsonschema.Draft202012Validator(schema).is_valid(extra)       # patient-svc cannot send other sexes
