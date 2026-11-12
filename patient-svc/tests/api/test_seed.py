"""Seed test (LLD §25.6): every demo scenario fact must survive a seed change, or CI fails."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import text

from app.cli.seed_patients import seed_scenarios
from app.db.session import create_sessionmaker
from app.domain.seed_ids import patient_id, user_id
from tests.conftest import make_settings

pytestmark = pytest.mark.api
TODAY = date(2026, 11, 11)


@pytest.fixture
async def seeded(db_engine, clock):
    sm = create_sessionmaker(db_engine)
    return await seed_scenarios(sm, make_settings(), clock)


async def detail(api, mrn: str) -> dict:
    r = await api.get(f"/patients/{patient_id(mrn)}")
    assert r.status_code == 200, (mrn, r.text)
    return r.json()


async def test_seed_is_idempotent_and_ids_are_deterministic(api, seeded, db_engine, clock):
    assert seeded == (10, 0)
    again = await seed_scenarios(create_sessionmaker(db_engine), make_settings(), clock)
    assert again == (0, 10)
    assert (await api.get("/patients")).json()["total"] == 10
    assert (await detail(api, "PT-000101"))["mrn"] == "PT-000101"
    assert patient_id("PT-000101") == patient_id("PT-000101") != patient_id("PT-000102")


async def test_next_registration_gets_pt_000111(api, seeded, make_patient):
    assert (await make_patient(first_name="Next"))["mrn"] == "PT-000111"


async def test_scenario_101_ramesh(api, seeded):
    d = await detail(api, "PT-000101")
    assert d["established_ckd_stage"] == "G3b" and d["allergy_status"] == "has_allergies"
    assert [a["allergen"] for a in d["allergy_summary"]] == ["Penicillin"]
    assert d["primary_diagnosis"]["icd10_code"] == "E11.21"
    assert d["counts"] == {"conditions": 4, "active_conditions": 4, "active_medications": 4, "encounters": 4}
    enc = (await api.get(f"/patients/{d['id']}/encounters")).json()
    assert sorted(e["status"] for e in enc["items"]) == ["draft", "final", "final", "final"]


async def test_scenario_102_clean_record(api, seeded):
    d = await detail(api, "PT-000102")
    assert d["established_ckd_stage"] == "G3a" and d["allergy_status"] == "nka" and d["counts"]["encounters"] == 2


async def test_scenario_103_unknown_allergy_and_final_without_vitals(api, seeded):
    d = await detail(api, "PT-000103")
    assert d["allergy_status"] == "unknown"
    enc = (await api.get(f"/patients/{d['id']}/encounters", params={"status": "final"})).json()["items"]
    assert enc and enc[0]["vitals_brief"] is None


async def test_scenario_104_two_allergies_one_severe_five_conditions(api, seeded):
    d = await detail(api, "PT-000104")
    assert d["established_ckd_stage"] == "G4" and d["counts"]["conditions"] == 5
    assert sorted(a["severity"] for a in d["allergy_summary"]) == ["moderate", "severe"]


async def test_scenario_105_no_medications_no_stage_nka(api, seeded):
    d = await detail(api, "PT-000105")
    assert d["counts"]["active_medications"] == 0 and d["established_ckd_stage"] is None
    assert d["allergy_status"] == "nka"


async def test_scenario_106_established_g4(api, seeded):
    assert (await detail(api, "PT-000106"))["established_ckd_stage"] == "G4"


async def test_scenario_107_last_encounter_about_230_days_ago(api, seeded):
    d = await detail(api, "PT-000107")
    assert d["last_visit"].startswith((TODAY - timedelta(days=230)).isoformat()[:7])
    assert abs((TODAY - date.fromisoformat(d["last_visit"][:10])).days - 230) <= 1


async def test_scenario_108_near_empty_chart(api, seeded):
    d = await detail(api, "PT-000108")
    assert d["past_medical_history"] and d["allergy_status"] == "unknown"
    assert d["counts"] == {"conditions": 0, "active_conditions": 0, "active_medications": 0, "encounters": 0}
    assert d["primary_diagnosis"] is None and d["last_visit"] is None


async def test_scenario_109_g5_latex_recent_visit_with_follow_up(api, seeded):
    d = await detail(api, "PT-000109")
    assert d["established_ckd_stage"] == "G5" and [a["allergen"] for a in d["allergy_summary"]] == ["Latex"]
    assert abs((TODAY - date.fromisoformat(d["last_visit"][:10])).days - 6) <= 1
    assert d["next_follow_up"] == (TODAY + timedelta(days=7)).isoformat()


async def test_scenario_110_lupus_active_medication_past_end_date(api, seeded):
    d = await detail(api, "PT-000110")
    assert d["established_ckd_stage"] is None and d["primary_diagnosis"]["icd10_code"] == "M32.14"
    row = next(i for i in (await api.get("/internal/patients/charts")).json()["items"]
               if i["mrn"] == "PT-000110")
    assert [m["name"] for m in row["active_meds_past_end"]] == ["Hydroxychloroquine"]


async def test_dashboard_shows_drafts_and_followups(api, seeded):
    drafts = (await api.get("/encounters", params={"status": "draft"})).json()
    assert drafts["total"] == 1 and drafts["items"][0]["mrn"] == "PT-000101"
    follow = (await api.get("/encounters", params={"upcoming_followups": "true", "limit": 10})).json()
    assert follow["total"] >= 4 and follow["items"][0]["mrn"] == "PT-000109"      # soonest first (+7 days)


async def test_seed_clinicians_use_deterministic_ids(api, seeded, db_engine):
    async with db_engine.connect() as conn:
        rows = (await conn.execute(text("SELECT DISTINCT clinician_id, clinician_name FROM encounters"))).all()
    assert {(r.clinician_id, r.clinician_name) for r in rows} == {
        (user_id("dr.rao@nephrocare.demo"), "Dr. Anita Rao"),
        (user_id("dr.malhotra@nephrocare.demo"), "Dr. Karan Malhotra")}
