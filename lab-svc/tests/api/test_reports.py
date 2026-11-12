"""Phase 6: create a report, unit conversion, snapshots, validation, corrections."""
from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from app.core.errors import UpstreamUnavailable

pytestmark = pytest.mark.api
WHEN = "2026-10-01T09:00:00Z"


@pytest.fixture
def post_report(api: httpx.AsyncClient) -> Callable[..., Any]:
    async def _post(pid: uuid.UUID, results: list[dict], when: str = WHEN, **extra: Any) -> httpx.Response:
        return await api.post(f"/labs/patients/{pid}/reports",
                              json={"collected_at": when, "results": results, **extra})
    return _post


def r(code: str, value: float, unit: str) -> dict:
    return {"test_code": code, "value": value, "unit": unit}


async def test_creates_report_with_flags_and_snapshots(patients, post_report) -> None:
    pid = patients.add("M")
    resp = await post_report(pid, [r("CREAT", 1.8, "mg/dL"), r("K", 6.5, "mmol/L"), r("EGFR", 38, "mL/min/1.73m²")],
                             lab_name="Lotus Lab", notes="fasting")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["lab_name"] == "Lotus Lab" and len(body["results"]) == 3
    by = {x["test_code"]: x for x in body["results"]}
    assert by["CREAT"]["flag"] == "high" and (by["CREAT"]["ref_low"], by["CREAT"]["ref_high"]) == (0.7, 1.3)
    assert by["K"]["flag"] == "critical_high" and by["EGFR"]["flag"] == "low"
    assert resp.headers["location"].startswith(f"/labs/patients/{pid}/results")


async def test_micromol_entry_is_converted_and_original_kept(patients, post_report) -> None:
    pid = patients.add("M")
    body = (await post_report(pid, [r("CREAT", 176.8, "µmol/L")])).json()["results"][0]
    assert (body["value"], body["unit"]) == (1.998, "mg/dL")
    assert (body["value_original"], body["unit_original"]) == (176.8, "µmol/L")


async def test_range_depends_on_patient_sex_from_patient_svc(patients, post_report) -> None:
    f, m = patients.add("F"), patients.add("M")
    assert (await post_report(f, [r("CREAT", 1.2, "mg/dL")])).json()["results"][0]["flag"] == "high"
    assert (await post_report(m, [r("CREAT", 1.2, "mg/dL")])).json()["results"][0]["flag"] == "normal"


async def test_sex_other_has_no_sex_specific_range_so_flag_is_unknown(patients, post_report) -> None:
    res = (await post_report(patients.add("O"), [r("CREAT", 1.2, "mg/dL"), r("K", 4, "mmol/L")])).json()["results"]
    assert {x["test_code"]: x["flag"] for x in res} == {"CREAT": "unknown", "K": "normal"}
    assert next(x for x in res if x["test_code"] == "CREAT")["ref_low"] is None


async def test_forwards_the_callers_token_and_request_id(patients, post_report, api) -> None:
    pid = patients.add()
    resp = await post_report(pid, [r("K", 4, "mmol/L")])
    (called, auth, rid), = patients.calls
    assert called == pid and auth == api.headers["Authorization"] and rid == resp.headers["x-request-id"]


async def test_ranges_revised_later_do_not_change_stored_flag(patients, post_report, db_engine, api, app) -> None:
    pid = patients.add("M")
    rid = (await post_report(pid, [r("K", 5.5, "mmol/L")])).json()["results"][0]["id"]
    async with db_engine.begin() as c:
        await c.execute(text("INSERT INTO lab_reference_ranges (test_code, low, high, effective_from, source) "
                             "VALUES ('K', 3.5, 6.0, '2026-06-01', 'test')"))
    app.state.catalog.invalidate()                      # the catalog is cached in process
    try:
        got = (await api.get(f"/labs/patients/{pid}/results")).json()["items"][0]
        assert got["id"] == rid and got["flag"] == "high" and got["ref_high"] == 5.0     # snapshot kept
        newer = (await post_report(pid, [r("K", 5.5, "mmol/L")], when="2026-10-02T09:00:00Z")).json()["results"][0]
        assert newer["flag"] == "normal" and newer["ref_high"] == 6.0                    # new rule applies
    finally:
        async with db_engine.begin() as c:
            await c.execute(text("TRUNCATE patient_lab_status, lab_results, lab_reports, audit_events"))
            await c.execute(text("DELETE FROM lab_reference_ranges WHERE effective_from = '2026-06-01'"))
        app.state.catalog.invalidate()


@pytest.mark.parametrize(("results", "field"), [
    ([r("CREAT", 1, "mmol/L")], "results[0].unit"),
    ([r("NOPE", 1, "mg/dL")], "results[0].test_code"),
    ([r("CREAT", 31, "mg/dL")], "results[0].value"),
    ([r("K", 4, "mmol/L"), r("K", 5, "mmol/L")], "results"),
])
async def test_invalid_results_are_422_and_nothing_is_stored(patients, post_report, db_engine, results, field) -> None:
    resp = await post_report(patients.add(), results)
    assert resp.status_code == 422 and resp.json()["error"]["code"] == "VALIDATION_ERROR"
    assert field in {d["field"] for d in resp.json()["error"]["details"]}
    async with db_engine.connect() as c:
        assert (await c.execute(text("SELECT count(*) FROM lab_reports"))).scalar_one() == 0


async def test_one_bad_analyte_rolls_back_the_whole_report(patients, post_report, db_engine) -> None:
    resp = await post_report(patients.add(), [r("K", 4, "mmol/L"), r("CREAT", 1, "mmol/L")])
    assert resp.status_code == 422
    async with db_engine.connect() as c:
        assert (await c.execute(text("SELECT count(*) FROM lab_results"))).scalar_one() == 0


async def test_negative_value_and_empty_results_rejected(patients, post_report) -> None:
    pid = patients.add()
    assert (await post_report(pid, [r("K", -1, "mmol/L")])).status_code == 422
    assert (await post_report(pid, [])).status_code == 422


async def test_future_date_rejected(patients, post_report) -> None:
    resp = await post_report(patients.add(), [r("K", 4, "mmol/L")], when="2026-11-12T12:00:00Z")   # clock: 11 Nov
    assert resp.status_code == 422 and resp.json()["error"]["details"][0]["field"] == "collected_at"


async def test_date_before_birth_rejected(patients, post_report) -> None:
    from datetime import date
    resp = await post_report(patients.add(dob=date(2020, 1, 1)), [r("K", 4, "mmol/L")], when="2019-01-01T00:00:00Z")
    assert resp.status_code == 422


async def test_naive_timestamp_rejected(patients, post_report) -> None:
    assert (await post_report(patients.add(), [r("K", 4, "mmol/L")], when="2026-10-01T09:00:00")).status_code == 422


async def test_unknown_patient_is_404_and_nothing_stored(post_report, db_engine) -> None:
    resp = await post_report(uuid.uuid4(), [r("K", 4, "mmol/L")])
    assert resp.status_code == 404
    async with db_engine.connect() as c:
        assert (await c.execute(text("SELECT count(*) FROM lab_reports"))).scalar_one() == 0


async def test_patient_svc_down_is_502_naming_the_upstream(patients, post_report) -> None:
    patients.error = UpstreamUnavailable("patient-svc")
    resp = await post_report(patients.add(), [r("K", 4, "mmol/L")])
    assert resp.status_code == 502 and resp.json()["error"]["code"] == "UPSTREAM_UNAVAILABLE"
    assert resp.json()["error"]["details"] == [{"upstream": "patient-svc"}]


async def test_requires_auth(client, patients) -> None:
    resp = await client.post(f"/labs/patients/{patients.add()}/reports",
                             json={"collected_at": WHEN, "results": [r("K", 4, "mmol/L")]})
    assert resp.status_code == 401


# ---- corrections ---------------------------------------------------------------------------------------
async def test_correction_supersedes_and_original_is_kept(patients, post_report, api, db_engine) -> None:
    pid = patients.add("M")
    orig = (await post_report(pid, [r("K", 6.5, "mmol/L")])).json()["results"][0]
    resp = await api.post(f"/labs/results/{orig['id']}/correct", json={"value": 4.5, "unit": "mmol/L", "reason": "re-checked against report"})
    assert resp.status_code == 201, resp.text
    new = resp.json()
    assert new["supersedes_id"] == orig["id"] and new["flag"] == "normal" and new["report_id"] == orig["report_id"]
    default = (await api.get(f"/labs/patients/{pid}/results")).json()
    assert [x["id"] for x in default["items"]] == [new["id"]] and default["total"] == 1
    full = (await api.get(f"/labs/patients/{pid}/results", params={"include_superseded": True})).json()
    assert full["total"] == 2
    async with db_engine.connect() as c:
        assert (await c.execute(text("SELECT value FROM lab_results WHERE id = :i"), {"i": orig["id"]})
                ).scalar_one() == 6.5                                     # never updated


async def test_correcting_twice_is_409(patients, post_report, api) -> None:
    orig = (await post_report(patients.add(), [r("K", 6.5, "mmol/L")])).json()["results"][0]
    assert (await api.post(f"/labs/results/{orig['id']}/correct", json={"value": 4, "unit": "mmol/L", "reason": "re-checked against report"})).status_code == 201
    again = await api.post(f"/labs/results/{orig['id']}/correct", json={"value": 5, "unit": "mmol/L", "reason": "re-checked against report"})
    assert again.status_code == 409 and again.json()["error"]["code"] == "ALREADY_CORRECTED"


async def test_correction_validates_unit_and_missing_result(patients, post_report, api) -> None:
    orig = (await post_report(patients.add(), [r("K", 6.5, "mmol/L")])).json()["results"][0]
    assert (await api.post(f"/labs/results/{orig['id']}/correct", json={"value": 4, "unit": "mg/dL", "reason": "re-checked against report"})).status_code == 422
    assert (await api.post(f"/labs/results/{uuid.uuid4()}/correct", json={"value": 4, "unit": "mmol/L", "reason": "re-checked against report"})).status_code == 404
