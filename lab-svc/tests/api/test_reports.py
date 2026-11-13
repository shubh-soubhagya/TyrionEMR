"""Phase 6: create a report and append a correction (LLD B6.1, B6.2, B7.2, B7.7, B8, B9, B13.2)."""
from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import jsonschema
import pytest
from sqlalchemy import text

from app.core.errors import UpstreamTimeout, UpstreamUnavailable
from app.main import create_app
from app.services.patient_client import PatientClient
from tests.conftest import make_settings

pytestmark = pytest.mark.api
WHEN = "2026-10-01T09:00:00Z"
CONTRACTS = Path(__file__).resolve().parents[2] / "contracts" / "lab"


@pytest.fixture
def post_report(api: httpx.AsyncClient) -> Callable[..., Any]:
    async def _post(pid: uuid.UUID, results: list[dict], when: str = WHEN, **extra: Any) -> httpx.Response:
        return await api.post(f"/labs/patients/{pid}/reports", json={"collected_at": when, "results": results, **extra})
    return _post


def r(code: str, value: Any, unit: str) -> dict:
    return {"test_code": code, "value": value, "unit": unit}


def errors(resp: httpx.Response) -> list[dict]:
    return resp.json()["error"]["details"]


async def count(db_engine, table: str) -> int:
    async with db_engine.connect() as c:
        return (await c.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()


async def with_extra_k_range(db_engine, app) -> None:
    async with db_engine.begin() as c:
        await c.execute(text("INSERT INTO lab_reference_ranges (test_code, low, high, effective_from, source) "
                             "VALUES ('K', 3.5, 6.0, '2026-06-01', 'test')"))
    app.state.catalog.invalidate()                      # the catalog is cached in process


async def drop_extra_k_range(db_engine, app) -> None:
    async with db_engine.begin() as c:
        await c.execute(text("TRUNCATE patient_lab_status, lab_results, lab_reports, audit_events"))
        await c.execute(text("DELETE FROM lab_reference_ranges WHERE effective_from = '2026-06-01'"))
    app.state.catalog.invalidate()


# ---- create: the happy path ----------------------------------------------------------------------
async def test_creates_report_with_flags_snapshots_and_summary(patients, post_report) -> None:
    pid = patients.add("M")
    resp = await post_report(pid, [r("CREAT", 1.8, "mg/dL"), r("K", 6.5, "mmol/L"), r("EGFR", 38, "mL/min/1.73m²")],
                             lab_name="Lotus Lab", notes="fasting")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["report"]["lab_name"] == "Lotus Lab" and body["report"]["notes"] == "fasting"
    assert body["report"]["patient_id"] == str(pid) and body["report"]["collected_at"] == "2026-10-01T09:00:00Z"
    by = {x["test_code"]: x for x in body["results"]}
    creat = by["CREAT"]
    assert (creat["flag"], creat["ref_low"], creat["ref_high"], creat["crit_high"]) == ("high", 0.7, 1.3, 5.0)
    assert by["K"]["flag"] == "critical_high" and by["K"]["crit_high"] == 6.0 and by["EGFR"]["flag"] == "low"
    assert body["summary"] == {"n": 3, "abnormal": 3, "critical": 1}
    assert resp.headers["location"] == f"/labs/patients/{pid}/results?report_id={body['report']['id']}"
    jsonschema.validate(body, json.loads((CONTRACTS / "report.schema.json").read_text(encoding="utf-8")))


async def test_status_row_is_written_in_the_same_transaction(patients, post_report, db_engine) -> None:
    pid = patients.add()
    await post_report(pid, [r("K", 4.0, "mmol/L")])
    async with db_engine.connect() as c:
        row = (await c.execute(text("SELECT result_count, version, rules_version FROM patient_lab_status "
                                    "WHERE patient_id = :p"), {"p": pid})).one()
    assert tuple(row) == (1, 1, "lab-rules-2")


async def test_lab_name_defaults_and_request_id_is_stored(patients, post_report, db_engine) -> None:
    resp = await post_report(patients.add(), [r("K", 4.0, "mmol/L")])
    assert resp.json()["report"]["lab_name"] == "Unspecified laboratory"
    async with db_engine.connect() as c:
        rid = (await c.execute(text("SELECT request_id FROM lab_reports"))).scalar_one()
    assert rid == resp.headers["x-request-id"]


async def test_values_may_be_numeric_strings(patients, post_report) -> None:
    resp = await post_report(patients.add("M"), [r("CREAT", "168", "µmol/L")])
    res = resp.json()["results"][0]
    assert (res["value"], res["unit"], res["value_original"], res["unit_original"]) == (1.898, "mg/dL", 168, "µmol/L")


@pytest.mark.parametrize("spelling", ["µmol/L", "μmol/L", "umol/L", "UMOL / L"])
async def test_unit_aliases_are_stored_in_the_catalog_spelling(patients, post_report, spelling) -> None:
    res = (await post_report(patients.add("M"), [r("CREAT", 150, spelling)])).json()["results"][0]
    assert res["value"] == 1.695 and res["unit_original"] == "µmol/L" and res["flag"] == "high"


async def test_range_depends_on_patient_sex_from_patient_svc(patients, post_report) -> None:
    f, m = patients.add("F"), patients.add("M")
    assert (await post_report(f, [r("CREAT", 1.2, "mg/dL")])).json()["results"][0]["flag"] == "high"
    assert (await post_report(m, [r("CREAT", 1.2, "mg/dL")])).json()["results"][0]["flag"] == "normal"


async def test_sex_other_has_no_sex_specific_range_so_flag_is_unknown(patients, post_report, db_engine) -> None:
    res = (await post_report(patients.add("O"), [r("CREAT", 1.2, "mg/dL"), r("K", 4, "mmol/L")])).json()["results"]
    by = {x["test_code"]: x for x in res}
    assert by["CREAT"]["flag"] == "unknown" and by["CREAT"]["ref_low"] is None and by["CREAT"]["crit_high"] is None
    assert by["K"]["flag"] == "normal"
    async with db_engine.connect() as c:
        assert (await c.execute(text("SELECT count(*) FROM lab_results WHERE flag = 'unknown' AND range_id IS NULL"))
                ).scalar_one() == 1


async def test_snapshot_records_which_range_applied(patients, post_report, db_engine) -> None:
    resp = await post_report(patients.add("F"), [r("CREAT", 1.0, "mg/dL")])
    async with db_engine.connect() as c:
        sex = (await c.execute(text("SELECT g.sex FROM lab_results r JOIN lab_reference_ranges g ON g.id = r.range_id "
                                    "WHERE r.id = :i"), {"i": resp.json()["results"][0]["id"]})).scalar_one()
    assert sex == "F"


async def test_forwards_the_callers_token_and_request_id(patients, post_report, api) -> None:
    pid = patients.add()
    resp = await post_report(pid, [r("K", 4, "mmol/L")])
    (called, auth, rid), = patients.calls
    assert called == pid and auth == api.headers["Authorization"] and rid == resp.headers["x-request-id"]


async def test_ranges_revised_later_do_not_change_stored_flag(patients, post_report, db_engine, api, app) -> None:
    pid = patients.add("M")
    first = (await post_report(pid, [r("K", 5.5, "mmol/L")])).json()["results"][0]
    await with_extra_k_range(db_engine, app)
    try:
        stored = (await api.get(f"/labs/patients/{pid}/results")).json()["items"][0]
        assert stored["id"] == first["id"] and stored["flag"] == "high" and stored["ref_high"] == 5.0   # snapshot kept
        newer = (await post_report(pid, [r("K", 5.5, "mmol/L")], when="2026-10-02T09:00:00Z")).json()["results"][0]
        assert newer["flag"] == "normal" and newer["ref_high"] == 6.0                    # the new rule applies
        old = (await post_report(pid, [r("K", 5.5, "mmol/L")], when="2026-03-01T09:00:00Z")).json()["results"][0]
        assert old["flag"] == "high" and old["ref_high"] == 5.0                          # range in force on the sample date
    finally:
        await drop_extra_k_range(db_engine, app)


# ---- create: validation (steps 2-6 collect every problem) ----------------------------------------
async def test_every_problem_is_returned_together_with_field_paths(patients, post_report, db_engine) -> None:
    resp = await post_report(patients.add("M"), [
        r("K", 4, "mmol/L"), r("K", 5, "mmol/L"), r("NOPE", 1, "mg/dL"), r("BUN", 10, "mmol/L"),
        r("CREAT", 31, "mg/dL")], when="2027-01-01T00:00:00Z")
    assert resp.status_code == 422
    err = resp.json()["error"]
    assert err["code"] == "VALIDATION_ERROR"                             # mixed problems
    by = {d["field"]: d for d in err["details"]}
    assert by["collected_at"]["code"] == "COLLECTED_AT_IN_FUTURE"
    assert by["results[1].test_code"]["code"] == "DUPLICATE_TEST_IN_REPORT"
    assert by["results[2].test_code"]["code"] == "UNKNOWN_TEST" and "K" in by["results[2].test_code"]["allowed"]
    unit = by["results[3].unit"]
    assert unit["code"] == "UNKNOWN_UNIT" and unit["allowed"] == ["mg/dL", "mmol/L (urea)"]
    assert by["results[4].value"]["code"] == "VALUE_IMPLAUSIBLE" and by["results[4].value"]["max"] == 30
    assert await count(db_engine, "lab_reports") == 0 and patients.calls == []     # nothing written, no upstream call


@pytest.mark.parametrize(("results", "when", "code", "field"), [
    ([r("CREAT", 1, "mmol/L")], WHEN, "UNKNOWN_UNIT", "results[0].unit"),
    ([r("NOPE", 1, "mg/dL")], WHEN, "UNKNOWN_TEST", "results[0].test_code"),
    ([r("CREAT", 31, "mg/dL")], WHEN, "VALUE_IMPLAUSIBLE", "results[0].value"),
    ([r("CREAT", 20000, "µmol/L")], WHEN, "VALUE_IMPLAUSIBLE", "results[0].value"),      # 226 mg/dL
    ([r("K", 4, "mmol/L"), r("K", 5, "mmol/L")], WHEN, "DUPLICATE_TEST_IN_REPORT", "results[1].test_code"),
    ([r("K", 4, "mmol/L")], "2026-11-12T12:00:00Z", "COLLECTED_AT_IN_FUTURE", "collected_at"),
])
async def test_single_problem_uses_its_specific_code(patients, post_report, db_engine, results, when, code, field) -> None:
    resp = await post_report(patients.add(), results, when=when)
    assert resp.status_code == 422 and resp.json()["error"]["code"] == code
    assert errors(resp)[0]["field"] == field
    assert await count(db_engine, "lab_reports") == 0


async def test_clock_skew_is_tolerated(patients, post_report) -> None:
    resp = await post_report(patients.add(), [r("K", 4, "mmol/L")], when="2026-11-11T12:00:30Z")     # clock 12:00:00
    assert resp.status_code == 201


@pytest.mark.parametrize("payload", [
    {"results": [r("K", -1, "mmol/L")]}, {"results": []}, {"results": [r("K", 1.23456, "mmol/L")]},
    {"results": [r("K", 4, "mmol/L")] * 9}, {"collected_at": "2026-10-01T09:00:00", "results": [r("K", 4, "mmol/L")]},
    {"lab_name": "x" * 121, "results": [r("K", 4, "mmol/L")]}, {"notes": "n" * 501, "results": [r("K", 4, "mmol/L")]},
])
async def test_schema_violations_are_422(patients, api, payload) -> None:
    body = {"collected_at": WHEN, **payload}
    resp = await api.post(f"/labs/patients/{patients.add()}/reports", json=body)
    assert resp.status_code == 422 and resp.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_schema_error_paths_use_brackets_and_never_echo_the_value(patients, api) -> None:
    bad = {"test_code": "K", "value": -7.77, "unit": "x"}
    resp = await api.post(f"/labs/patients/{patients.add()}/reports",
                          json={"collected_at": WHEN, "results": [r("K", 4, "mmol/L"), bad]})
    assert errors(resp)[0]["field"] == "results[1].value"
    assert "7.77" not in resp.text


async def test_date_before_birth_rejected_after_the_patient_lookup(patients, post_report) -> None:
    pid = patients.add(dob=date(2020, 1, 1))
    resp = await post_report(pid, [r("K", 4, "mmol/L")], when="2019-01-01T00:00:00Z")
    assert resp.status_code == 422 and resp.json()["error"]["code"] == "COLLECTED_BEFORE_BIRTH"
    assert len(patients.calls) == 1


# ---- create: patient-svc -------------------------------------------------------------------------
async def test_unknown_patient_is_404_with_the_id(post_report, db_engine) -> None:
    pid = uuid.uuid4()
    resp = await post_report(pid, [r("K", 4, "mmol/L")])
    assert resp.status_code == 404 and resp.json()["error"]["code"] == "PATIENT_NOT_FOUND"
    assert errors(resp) == [{"patient_id": str(pid)}]
    assert await count(db_engine, "lab_reports") == 0


@pytest.mark.parametrize(("exc", "status", "code"), [
    (UpstreamUnavailable("patient-svc"), 502, "UPSTREAM_UNAVAILABLE"),
    (UpstreamTimeout("patient-svc"), 504, "UPSTREAM_TIMEOUT")])
async def test_patient_svc_failure_names_the_upstream_and_writes_nothing(
        patients, post_report, db_engine, exc, status, code) -> None:
    patients.error = exc
    resp = await post_report(patients.add(), [r("K", 4, "mmol/L")])
    assert resp.status_code == status and resp.json()["error"]["code"] == code
    assert errors(resp) == [{"upstream": "patient-svc"}]
    assert await count(db_engine, "lab_reports") == 0 and await count(db_engine, "audit_events") == 0


async def test_a_transient_patient_svc_failure_is_retried_end_to_end(jwks, clock, sign, db_engine) -> None:
    """503 then 200: the real client retries and the report is created (B13.2)."""
    pid, calls = uuid.uuid4(), []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.headers["authorization"])
        if len(calls) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"id": str(pid), "sex": "M", "date_of_birth": "1959-04-17"})

    settings = make_settings()
    app = create_app(settings, clock=clock, jwks=jwks, patients=PatientClient(settings, httpx.MockTransport(handler)))
    async with app.router.lifespan_context(app):
        await jwks.refresh("test")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            resp = await c.post(f"/labs/patients/{pid}/reports", headers={"Authorization": f"Bearer {sign()}"},
                                json={"collected_at": WHEN, "results": [r("K", 4, "mmol/L")]})
    assert resp.status_code == 201 and len(calls) == 2 and len(set(calls)) == 1
    assert await count(db_engine, "lab_reports") == 1


async def test_requires_auth(client, patients) -> None:
    resp = await client.post(f"/labs/patients/{patients.add()}/reports",
                             json={"collected_at": WHEN, "results": [r("K", 4, "mmol/L")]})
    assert resp.status_code == 401


# ---- corrections ---------------------------------------------------------------------------------
async def correct(api, rid, value, unit="mmol/L", reason="re-checked against the printed report") -> httpx.Response:
    return await api.post(f"/labs/results/{rid}/correct", json={"value": value, "unit": unit, "reason": reason})


async def test_correction_supersedes_and_the_original_is_kept(patients, post_report, api, db_engine) -> None:
    pid = patients.add("M")
    orig = (await post_report(pid, [r("K", 6.5, "mmol/L")])).json()["results"][0]
    calls_before = len(patients.calls)
    resp = await correct(api, orig["id"], 4.5)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["corrected"] == {"id": orig["id"], "value": 6.5, "flag": "critical_high", "superseded": True}
    cur = body["current"]
    assert cur["supersedes_id"] == orig["id"] and cur["flag"] == "normal" and cur["value"] == 4.5
    assert cur["correction_reason"] == "re-checked against the printed report" and body["status_version"] == 2
    assert len(patients.calls) == calls_before                           # a correction never calls patient-svc
    jsonschema.validate(body, json.loads((CONTRACTS / "correction.schema.json").read_text(encoding="utf-8")))
    default = (await api.get(f"/labs/patients/{pid}/results")).json()
    assert [x["id"] for x in default["items"]] == [cur["id"]] and default["total"] == 1
    assert (await api.get(f"/labs/patients/{pid}/results", params={"include_superseded": True})).json()["total"] == 2
    async with db_engine.connect() as c:
        assert (await c.execute(text("SELECT value FROM lab_results WHERE id = :i"), {"i": orig["id"]})
                ).scalar_one() == 6.5                                    # never updated


async def test_correction_is_judged_against_the_targets_snapshot(patients, post_report, api, db_engine, app) -> None:
    pid = patients.add("M")
    orig = (await post_report(pid, [r("K", 5.5, "mmol/L")])).json()["results"][0]          # high against 3.5-5.0
    await with_extra_k_range(db_engine, app)
    try:
        cur = (await correct(api, orig["id"], 5.6)).json()["current"]
        assert cur["flag"] == "high" and cur["ref_high"] == 5.0                               # same range as the original
    finally:
        await drop_extra_k_range(db_engine, app)


async def test_correction_recomputes_the_read_model(patients, post_report, api) -> None:
    pid = patients.add()
    orig = (await post_report(pid, [r("K", 6.8, "mmol/L")])).json()["results"][0]
    assert (await api.get(f"/labs/patients/{pid}/latest")).json()["has_critical"] is True
    await correct(api, orig["id"], 4.2)
    latest = (await api.get(f"/labs/patients/{pid}/latest")).json()
    k = next(t for t in latest["tests"] if t["test_code"] == "K")["result"]
    assert latest["has_critical"] is False and k["value"] == 4.2


async def test_correcting_the_old_id_again_is_409_with_the_current_id(patients, post_report, api) -> None:
    orig = (await post_report(patients.add(), [r("K", 6.5, "mmol/L")])).json()["results"][0]
    first = (await correct(api, orig["id"], 4.0)).json()["current"]
    again = await correct(api, orig["id"], 5.0)
    assert again.status_code == 409 and again.json()["error"]["code"] == "RESULT_ALREADY_SUPERSEDED"
    assert errors(again) == [{"current_id": first["id"]}]
    assert (await correct(api, first["id"], 5.0)).status_code == 201     # the current value can be corrected again


async def test_two_concurrent_corrections_one_wins(patients, post_report, api) -> None:
    orig = (await post_report(patients.add(), [r("K", 6.5, "mmol/L")])).json()["results"][0]
    a, b = await asyncio.gather(correct(api, orig["id"], 4.0), correct(api, orig["id"], 4.1))
    assert sorted([a.status_code, b.status_code]) == [201, 409]


async def test_correction_with_the_same_value_is_no_change(patients, post_report, api) -> None:
    orig = (await post_report(patients.add(), [r("K", 6.5, "mmol/L")])).json()["results"][0]
    resp = await correct(api, orig["id"], 6.5, unit="mEq/L")             # same canonical value, other unit spelling
    assert resp.status_code == 422 and resp.json()["error"]["code"] == "NO_CHANGE"


async def test_correction_validation(patients, post_report, api) -> None:
    orig = (await post_report(patients.add(), [r("K", 6.5, "mmol/L")])).json()["results"][0]
    bad_unit = await correct(api, orig["id"], 4, unit="mg/dL")
    assert bad_unit.status_code == 422 and bad_unit.json()["error"]["code"] == "UNKNOWN_UNIT"
    assert (await correct(api, orig["id"], 40)).json()["error"]["code"] == "VALUE_IMPLAUSIBLE"
    for bad in ({"value": 4, "unit": "mmol/L"}, {"value": 4, "unit": "mmol/L", "reason": "no"},
                {"value": 4, "unit": "mmol/L", "reason": "x" * 301}):
        assert (await api.post(f"/labs/results/{orig['id']}/correct", json=bad)).status_code == 422
    missing = uuid.uuid4()
    nf = await correct(api, missing, 4)
    assert nf.status_code == 404 and nf.json()["error"]["code"] == "RESULT_NOT_FOUND"
    assert errors(nf) == [{"result_id": str(missing)}]
