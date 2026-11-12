"""Encounters: draft, edit, finalize, delete, problem-list linkage, concurrency (LLD §25.2, §25.4)."""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.api

VISIT = "2026-11-11T10:15:00+05:30"


def enc_body(**kw):
    body = {"encounter_date": VISIT, "encounter_type": "follow_up", "chief_complaint": "Review of labs",
            "symptoms": ["Fatigue", "fatigue"], "examination_notes": "BP 138/82",
            "assessment": "Persistent eGFR decline", "plan": "Follow-up in 6 weeks",
            "follow_up_date": "2026-12-23",
            "vitals": {"systolic_bp": 138, "diastolic_bp": 82, "heart_rate": 74, "temperature_c": 36.65,
                       "weight_kg": 72.9},
            "diagnoses": [{"icd10_code": "n18.32", "description": "Chronic kidney disease, stage 3b",
                           "add_to_problem_list": True}], "status": "draft"}
    body.update(kw)
    return body


@pytest.fixture
async def pid(make_patient) -> str:
    return (await make_patient())["id"]


async def create(api, pid, **kw):
    return await api.post(f"/patients/{pid}/encounters", json=enc_body(**kw))


async def test_create_draft_roundtrip(api, pid):
    r = await create(api, pid)
    assert r.status_code == 201, r.text
    enc = r.json()["encounter"]
    assert r.json()["problem_list_changes"] == {"added": 0, "reactivated": 0, "linked": 0}
    assert enc["status"] == "draft" and enc["version"] == 1 and enc["finalized_at"] is None
    assert enc["symptoms"] == ["Fatigue"]                              # de-duplicated case-insensitively
    assert enc["vitals"]["temperature_c"] == 36.7                       # 36.65 rounds half-up, not rejected
    assert enc["diagnoses"][0]["icd10_code"] == "N18.32" and enc["diagnoses"][0]["condition_id"] is None
    assert enc["clinician_name"] == "Dr. Test"                          # from the JWT, never the body
    assert r.headers["location"].endswith(f"/encounters/{enc['id']}")
    got = await api.get(f"/patients/{pid}/encounters/{enc['id']}")
    assert got.json() == enc
    assert (await api.get(f"/patients/{pid}")).json()["counts"]["conditions"] == 0   # P-04: no linkage on draft


async def test_clinician_fields_in_body_are_rejected(api, pid):
    r = await create(api, pid, clinician_name="Dr. Evil")
    assert r.status_code == 422


async def test_no_vitals_stores_no_row(api, pid, db_engine):
    for vitals in (None, {}, {"heart_rate": None}):
        r = await create(api, pid, vitals=vitals)
        assert r.status_code == 201 and r.json()["encounter"]["vitals"] is None
    async with db_engine.connect() as conn:
        assert (await conn.execute(text("SELECT count(*) FROM encounter_vitals"))).scalar_one() == 0


@pytest.mark.parametrize("vitals,field,issue", [
    ({"systolic_bp": 49}, "vitals.systolic_bp", "Enter 50 to 300 mmHg."),
    ({"systolic_bp": 301}, "vitals.systolic_bp", "Enter 50 to 300 mmHg."),
    ({"heart_rate": 19}, "vitals.heart_rate", "Enter 20 to 300 bpm."),
    ({"temperature_c": 29.9}, "vitals.temperature_c", "Enter 30 to 45 °C."),
    ({"weight_kg": 0.5}, "vitals.weight_kg", "Enter 1 to 500 kg."),
    ({"systolic_bp": 80, "diastolic_bp": 80}, "vitals", "Systolic must be higher than diastolic."),
])
async def test_vitals_validation(api, pid, vitals, field, issue):
    r = await create(api, pid, vitals=vitals)
    assert r.status_code == 422
    assert {"field": field, "issue": issue} in r.json()["error"]["details"]


async def test_vitals_boundaries_accepted(api, pid):
    r = await create(api, pid, vitals={"systolic_bp": 50, "diastolic_bp": 20, "heart_rate": 300})
    assert r.status_code == 201


async def test_date_rules(api, pid):
    soon = await create(api, pid, encounter_date="2026-11-11T17:30:59+05:30")        # now + 59 s
    assert soon.status_code == 201
    later = await create(api, pid, encounter_date="2026-11-11T17:31:01+05:30")       # now + 61 s
    assert later.json()["error"]["details"][0] == {"field": "encounter_date",
                                                   "issue": "Visit date cannot be in the future."}
    before = await create(api, pid, follow_up_date="2026-11-10")
    assert {"field": "follow_up_date", "issue": "Follow-up cannot be before the visit."} in \
        before.json()["error"]["details"]
    same_day = await create(api, pid, follow_up_date="2026-11-11")
    assert same_day.status_code == 201
    dob = await create(api, pid, encounter_date="1950-01-01T10:00:00+05:30", follow_up_date=None)
    assert dob.status_code == 422


async def test_diagnosis_rules(api, pid):
    dup = await create(api, pid, diagnoses=[{"icd10_code": "N18.3", "description": "a"},
                                            {"icd10_code": "n18.3", "description": "b"}])
    assert dup.status_code == 422
    blank = await create(api, pid, diagnoses=[{"description": "  "}])
    assert blank.json()["error"]["details"][0]["issue"] == "Each diagnosis needs a description."
    assert (await create(api, pid, diagnoses=[{"description": "x"}] * 21)).status_code == 422


async def test_finalize_requires_cc_assessment_plan(api, pid):
    r = await create(api, pid, status="final", plan="   ", chief_complaint=None)
    assert r.status_code == 422
    fields = {d["field"] for d in r.json()["error"]["details"]}
    assert fields == {"chief_complaint", "plan"}
    assert (await api.get(f"/patients/{pid}/encounters")).json()["total"] == 0        # whole create rolled back


async def test_create_final_adds_to_problem_list(api, pid):
    r = await create(api, pid, status="final")
    assert r.status_code == 201, r.text
    assert r.json()["problem_list_changes"] == {"added": 1, "reactivated": 0, "linked": 0}
    enc = r.json()["encounter"]
    assert enc["status"] == "final" and enc["finalized_at"] and enc["version"] == 2
    conds = (await api.get(f"/patients/{pid}/conditions")).json()["items"]
    assert len(conds) == 1
    c = conds[0]
    assert c["icd10_code"] == "N18.32" and c["category"] == "nephrology" and c["is_primary"] is False
    assert c["source_encounter_id"] == enc["id"] and c["onset_date"] == "2026-11-11"
    assert enc["diagnoses"][0]["condition_id"] == c["id"]


async def test_same_icd_links_resolved_reactivates(api, pid):
    await create(api, pid, status="final")
    again = await create(api, pid, status="final")
    assert again.json()["problem_list_changes"] == {"added": 0, "reactivated": 0, "linked": 1}
    cid = (await api.get(f"/patients/{pid}/conditions")).json()["items"][0]["id"]
    await api.patch(f"/patients/{pid}/conditions/{cid}", json={"status": "resolved"})
    third = await create(api, pid, status="final")
    assert third.json()["problem_list_changes"] == {"added": 0, "reactivated": 1, "linked": 0}
    items = (await api.get(f"/patients/{pid}/conditions")).json()["items"]
    assert len(items) == 1 and items[0]["status"] == "active" and items[0]["resolved_date"] is None


async def test_no_icd_links_by_description_and_unflagged_dx_skipped(api, pid):
    dx = [{"description": "Anaemia of CKD", "add_to_problem_list": True},
          {"icd10_code": "I10", "description": "Hypertension", "add_to_problem_list": False}]
    first = await create(api, pid, status="final", diagnoses=dx)
    assert first.json()["problem_list_changes"]["added"] == 1
    second = await create(api, pid, status="final", diagnoses=[{**dx[0], "description": "anaemia of ckd"}])
    assert second.json()["problem_list_changes"] == {"added": 0, "reactivated": 0, "linked": 1}
    assert len((await api.get(f"/patients/{pid}/conditions")).json()["items"]) == 1


async def test_encounter_never_sets_primary_and_category_inference(api, pid):
    dx = [{"icd10_code": "E11.21", "description": "T2DM nephropathy", "add_to_problem_list": True},
          {"icd10_code": "I10", "description": "Hypertension", "add_to_problem_list": True},
          {"icd10_code": "E78.5", "description": "Lipids", "add_to_problem_list": True, "category": "nephrology"}]
    await create(api, pid, status="final", diagnoses=dx)
    by_icd = {c["icd10_code"]: c for c in (await api.get(f"/patients/{pid}/conditions")).json()["items"]}
    assert by_icd["E11.21"]["category"] == "nephrology" and by_icd["I10"]["category"] == "comorbidity"
    assert by_icd["E78.5"]["category"] == "nephrology"                  # explicit category wins
    assert not any(c["is_primary"] for c in by_icd.values())


async def test_edit_draft_replaces_children_and_bumps_version(api, pid):
    enc = (await create(api, pid)).json()["encounter"]
    url = f"/patients/{pid}/encounters/{enc['id']}"
    r = await api.patch(url, json={"version": 1, "plan": "New plan", "vitals": {"heart_rate": 80},
                                   "diagnoses": [{"description": "Only one"}]})
    body = r.json()["encounter"]
    assert r.status_code == 200 and body["version"] == 2 and body["plan"] == "New plan"
    assert body["vitals"]["heart_rate"] == 80 and body["vitals"]["systolic_bp"] is None
    assert [d["description"] for d in body["diagnoses"]] == ["Only one"]
    kept = await api.patch(url, json={"version": 2, "chief_complaint": "Changed"})
    assert kept.json()["encounter"]["vitals"]["heart_rate"] == 80          # not sent -> untouched
    cleared = await api.patch(url, json={"version": 3, "vitals": None, "follow_up_date": None})
    assert cleared.json()["encounter"]["vitals"] is None and cleared.json()["encounter"]["follow_up_date"] is None
    stale = await api.patch(url, json={"version": 1, "plan": "x"})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "VERSION_CONFLICT"
    assert (await api.patch(url, json={"version": 4, "status": None})).status_code == 422


async def test_patch_status_final_finalizes_atomically(api, pid):
    enc = (await create(api, pid, plan=None)).json()["encounter"]
    url = f"/patients/{pid}/encounters/{enc['id']}"
    bad = await api.patch(url, json={"version": 1, "status": "final"})          # plan missing
    assert bad.status_code == 422
    still = (await api.get(url)).json()
    assert still["status"] == "draft" and still["version"] == 1 and still["diagnoses"][0]["condition_id"] is None
    ok = await api.patch(url, json={"version": 1, "status": "final", "plan": "Now there is a plan"})
    assert ok.status_code == 200
    assert ok.json()["problem_list_changes"]["added"] == 1 and ok.json()["encounter"]["status"] == "final"


async def test_finalize_endpoint(api, pid):
    enc = (await create(api, pid)).json()["encounter"]
    url = f"/patients/{pid}/encounters/{enc['id']}/finalize"
    assert (await api.post(url, json={"version": 9})).status_code == 409
    r = await api.post(url, json={"version": 1})
    assert r.status_code == 200 and r.json()["encounter"]["status"] == "final"
    assert r.json()["problem_list_changes"]["added"] == 1
    again = await api.post(url, json={"version": 2})
    assert again.status_code == 409 and again.json()["error"]["code"] == "ENCOUNTER_FINAL"


async def test_final_is_immutable_via_api(api, pid):
    enc = (await create(api, pid, status="final")).json()["encounter"]
    url = f"/patients/{pid}/encounters/{enc['id']}"
    edit = await api.patch(url, json={"version": enc["version"], "plan": "tamper"})
    assert edit.status_code == 409 and edit.json()["error"]["code"] == "ENCOUNTER_FINAL"
    assert edit.json()["error"]["message"] == "Final encounters cannot be edited."
    gone = await api.delete(url)
    assert gone.status_code == 409 and gone.json()["error"]["message"] == "Final encounters cannot be deleted."
    assert (await api.get(url)).json()["plan"] == "Follow-up in 6 weeks"


async def test_delete_draft_hides_it(api, pid):
    enc = (await create(api, pid)).json()["encounter"]
    url = f"/patients/{pid}/encounters/{enc['id']}"
    assert (await api.delete(url)).status_code == 204
    assert (await api.get(url)).status_code == 404
    assert (await api.get(f"/patients/{pid}/encounters")).json()["total"] == 0
    assert (await api.delete(url)).status_code == 404
    assert (await api.get(f"/patients/{pid}")).json()["counts"]["encounters"] == 0


async def test_history_order_filter_paging_and_shape(api, pid):
    await create(api, pid, status="final", encounter_date="2026-10-01T10:00:00+05:30")
    await create(api, pid, status="final", encounter_date="2026-10-21T10:00:00+05:30", vitals=None)
    await create(api, pid, encounter_date="2026-11-05T10:00:00+05:30")                       # draft
    h = (await api.get(f"/patients/{pid}/encounters")).json()
    assert [i["status"] for i in h["items"]] == ["draft", "final", "final"] and h["total"] == 3
    assert h["items"][2]["vitals_brief"] == {"systolic_bp": 138, "diastolic_bp": 82, "heart_rate": 74}
    assert h["items"][1]["vitals_brief"] is None
    only = (await api.get(f"/patients/{pid}/encounters", params={"status": "final"})).json()
    assert only["total"] == 2
    page2 = (await api.get(f"/patients/{pid}/encounters", params={"size": 2, "page": 2})).json()
    assert len(page2["items"]) == 1 and page2["total"] == 3
    detail = (await api.get(f"/patients/{pid}")).json()
    assert detail["last_visit"].startswith("2026-10-21") and detail["counts"]["encounters"] == 3


async def test_next_follow_up_is_earliest_future_among_finals(api, pid):
    await create(api, pid, status="final", follow_up_date="2026-11-01", encounter_date="2026-10-01T10:00:00+05:30")
    await create(api, pid, status="final", follow_up_date="2026-12-23")
    await create(api, pid, status="final", follow_up_date="2026-12-02")
    await create(api, pid, follow_up_date="2026-11-20")                                   # draft: ignored
    assert (await api.get(f"/patients/{pid}")).json()["next_follow_up"] == "2026-12-02"


async def test_encounter_of_another_patient_is_404(api, pid, make_patient):
    other = (await make_patient(first_name="Z"))["id"]
    enc = (await create(api, pid)).json()["encounter"]
    assert (await api.get(f"/patients/{other}/encounters/{enc['id']}")).status_code == 404
    assert (await api.patch(f"/patients/{other}/encounters/{enc['id']}", json={"version": 1})).status_code == 404
    deleted = (await api.delete(f"/patients/{pid}"))
    assert deleted.status_code == 204
    assert (await api.get(f"/patients/{pid}/encounters/{enc['id']}")).status_code == 404
    assert (await create(api, pid)).status_code == 404


# ---------------------------------- concurrency (LLD §25.4) ---------------------------------------
async def test_concurrent_finalize_and_edit_one_conflicts(api, pid):
    enc = (await create(api, pid)).json()["encounter"]
    base = f"/patients/{pid}/encounters/{enc['id']}"
    fin, edit = await asyncio.gather(api.post(f"{base}/finalize", json={"version": 1}),
                                     api.patch(base, json={"version": 1, "plan": "edited"}))
    codes = sorted([fin.status_code, edit.status_code])
    assert codes[0] in (200,) and codes[1] == 409, (fin.text, edit.text)
    final = (await api.get(base)).json()
    assert final["status"] == "final" or final["plan"] == "edited"


async def test_concurrent_double_finalize_adds_condition_once(api, pid):
    enc = (await create(api, pid)).json()["encounter"]
    url = f"/patients/{pid}/encounters/{enc['id']}/finalize"
    a, b = await asyncio.gather(api.post(url, json={"version": 1}), api.post(url, json={"version": 1}))
    assert sorted([a.status_code, b.status_code]) == [200, 409]
    assert len((await api.get(f"/patients/{pid}/conditions")).json()["items"]) == 1
