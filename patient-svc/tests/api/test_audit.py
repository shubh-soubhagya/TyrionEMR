"""Audit trail (LLD §19, §25.2 Audit): one row per write, names not values, nothing for failed writes."""
from __future__ import annotations

import json

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.api

SECRET = "ZZ-SECRET-VALUE-9931"


async def rows(db_engine, where: str = "true"):
    async with db_engine.connect() as conn:
        res = await conn.execute(text("SELECT action, resource, patient_id, resource_id, request_id, details, "
                                      f"actor_id FROM audit_events WHERE {where} ORDER BY id"))
        return [dict(r) for r in res.mappings().all()]


async def test_each_write_produces_exactly_one_row_with_field_names_only(api, db_engine, make_patient):
    p = await make_patient(past_medical_history=SECRET, phone="+91 9876543210")
    pid = p["id"]
    await api.patch(f"/patients/{pid}", json={"version": 1, "phone": "+91 9000000000",
                                              "established_ckd_stage": "G4"})
    cond = (await api.post(f"/patients/{pid}/conditions", json={
        "description": SECRET, "category": "nephrology", "is_primary": True})).json()
    await api.patch(f"/patients/{pid}/conditions/{cond['id']}", json={"status": "resolved"})
    med = (await api.post(f"/patients/{pid}/medications", json={
        "name": SECRET, "dose": "5 mg", "frequency": "daily"})).json()
    await api.patch(f"/patients/{pid}/medications/{med['id']}", json={"dose": "10 mg"})
    await api.patch(f"/patients/{pid}/medications/{med['id']}", json={"action": "discontinue"})
    al = (await api.post(f"/patients/{pid}/allergies", json={"allergen": SECRET, "reaction": SECRET})).json()
    await api.delete(f"/patients/{pid}/allergies/{al['allergy']['id']}")
    await api.delete(f"/patients/{pid}/conditions/{cond['id']}")
    await api.delete(f"/patients/{pid}")

    got = await rows(db_engine)
    assert [r["action"] for r in got] == [
        "patient.create", "patient.update", "condition.add", "condition.update", "medication.add",
        "medication.update", "medication.discontinue", "allergy.add", "allergy.remove", "condition.delete",
        "patient.delete"]
    assert all(str(r["patient_id"]) == pid and r["request_id"].startswith("req-") for r in got)
    assert SECRET not in json.dumps([r["details"] for r in got]), "audit details must never hold values"
    assert got[1]["details"] == {"fields": ["established_ckd_stage", "phone"]}


async def test_encounter_audit_actions_and_problem_list_details(api, db_engine, make_patient):
    pid = (await make_patient())["id"]
    base = {"encounter_date": "2026-11-11T10:00:00+05:30", "chief_complaint": SECRET, "assessment": "a", "plan": "p",
            "diagnoses": [{"icd10_code": "N18.32", "description": "CKD", "add_to_problem_list": True}]}
    draft = (await api.post(f"/patients/{pid}/encounters", json=base)).json()["encounter"]
    await api.patch(f"/patients/{pid}/encounters/{draft['id']}", json={"version": 1, "plan": "p2"})
    await api.post(f"/patients/{pid}/encounters/{draft['id']}/finalize", json={"version": 2})
    other = (await api.post(f"/patients/{pid}/encounters", json={**base, "status": "final"})).json()["encounter"]
    gone = (await api.post(f"/patients/{pid}/encounters", json=base)).json()["encounter"]
    await api.delete(f"/patients/{pid}/encounters/{gone['id']}")
    await api.get(f"/patients/{pid}/encounters/{other['id']}")

    got = await rows(db_engine, "resource = 'encounter'")
    assert [r["action"] for r in got] == [
        "encounter.create_draft", "encounter.update_draft", "encounter.finalize", "encounter.finalize",
        "encounter.create_draft", "encounter.delete_draft", "encounter.view"]
    assert got[2]["details"]["problem_list"] == {"added": 1, "reactivated": 0, "linked": 0}
    assert got[3]["details"]["problem_list"] == {"added": 0, "reactivated": 0, "linked": 1}
    assert SECRET not in json.dumps([r["details"] for r in got])


async def test_reads_audited_but_lists_search_and_dashboard_are_not(api, db_engine, make_patient):
    pid = (await make_patient())["id"]
    await api.get(f"/patients/{pid}")
    await api.get("/patients", params={"q": "kul"})
    await api.get(f"/patients/{pid}/conditions")
    await api.get(f"/patients/{pid}/encounters")
    await api.get("/encounters", params={"status": "draft"})
    actions = [r["action"] for r in await rows(db_engine)]
    assert actions == ["patient.create", "patient.view"]


async def test_failed_writes_leave_no_audit_row(api, db_engine, make_patient):
    pid = (await make_patient())["id"]
    before = len(await rows(db_engine))
    assert (await api.patch(f"/patients/{pid}", json={"version": 9, "phone": None})).status_code == 409
    assert (await api.post(f"/patients/{pid}/encounters", json={
        "encounter_date": "2026-11-11T10:00:00+05:30", "status": "final"})).status_code == 422
    assert (await api.post(f"/patients/{pid}/allergies", json={"allergen": "A"})).status_code == 201
    assert (await api.post(f"/patients/{pid}/allergies", json={"allergen": "a"})).status_code == 409
    assert (await api.get("/patients/00000000-0000-0000-0000-000000000000")).status_code == 404
    after = [r["action"] for r in (await rows(db_engine))[before:]]
    assert after == ["allergy.add"]


async def test_actor_is_the_token_subject(api, db_engine, make_patient, sign):
    sub = "5b1e0000-0000-4000-8000-000000000001"
    api.headers["Authorization"] = f"Bearer {sign(sub=sub)}"
    await make_patient()
    assert [str(r["actor_id"]) for r in await rows(db_engine)] == [sub]


async def test_business_metrics_and_logs_carry_counts_only(api, make_patient):
    import logging

    from app.core.metrics import ENCOUNTERS_FINALIZED, OPTIMISTIC_CONFLICTS, PROBLEM_LIST_CHANGES
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[method-assign]
    logging.getLogger("patient").addHandler(handler)
    logging.getLogger("patient").setLevel(logging.INFO)
    pid = (await make_patient())["id"]
    fin0 = ENCOUNTERS_FINALIZED._value.get()
    added0 = PROBLEM_LIST_CHANGES.labels(kind="added")._value.get()
    conflicts0 = OPTIMISTIC_CONFLICTS.labels(resource="patient")._value.get()
    r = await api.post(f"/patients/{pid}/encounters", json={
        "encounter_date": "2026-11-11T10:00:00+05:30", "chief_complaint": SECRET, "assessment": "a", "plan": "p",
        "status": "final", "diagnoses": [{"icd10_code": "N18.32", "description": "CKD", "add_to_problem_list": True}]})
    assert r.status_code == 201
    await api.patch(f"/patients/{pid}", json={"version": 9, "phone": None})
    assert ENCOUNTERS_FINALIZED._value.get() == fin0 + 1
    assert PROBLEM_LIST_CHANGES.labels(kind="added")._value.get() == added0 + 1
    assert OPTIMISTIC_CONFLICTS.labels(resource="patient")._value.get() == conflicts0 + 1
    logging.getLogger("patient").removeHandler(handler)
    out = " ".join(f"{r.getMessage()} {r.__dict__}" for r in records)
    assert "encounter.finalized" in out and "version_conflict" in out
    assert SECRET not in out and "Kulkarni" not in out
    text = (await api.get("/metrics")).text
    assert "db_pool_checked_out" in text and "encounters_finalized_total" in text
