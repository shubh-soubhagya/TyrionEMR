"""Conditions, medications, allergies (LLD §25.2)."""
from __future__ import annotations

import asyncio

import pytest

pytestmark = pytest.mark.api


@pytest.fixture
async def pid(make_patient) -> str:
    return (await make_patient())["id"]


async def _cond(api, pid, **kw):
    body = {"description": "Chronic kidney disease, stage 3b", "category": "nephrology", **kw}
    return await api.post(f"/patients/{pid}/conditions", json=body)


# ---------------------------------- conditions ----------------------------------------------------
async def test_condition_create_uppercases_icd_and_validates(api, pid):
    r = await _cond(api, pid, icd10_code="n18.32")
    assert r.status_code == 201 and r.json()["icd10_code"] == "N18.32" and r.json()["is_primary"] is False
    assert (await _cond(api, pid, icd10_code="12345")).status_code == 422
    future = await _cond(api, pid, onset_date="2026-11-12")
    assert future.json()["error"]["details"][0]["issue"] == "Onset cannot be in the future."
    assert (await api.post(f"/patients/{pid}/conditions", json={"description": " ", "category": "nephrology"})
            ).status_code == 422


async def test_second_primary_clears_the_first(api, pid):
    a = (await _cond(api, pid, is_primary=True, description="A")).json()
    b = (await _cond(api, pid, is_primary=True, description="B")).json()
    items = (await api.get(f"/patients/{pid}/conditions")).json()["items"]
    assert [i["id"] for i in items if i["is_primary"]] == [b["id"]] and a["id"] != b["id"]
    detail = (await api.get(f"/patients/{pid}")).json()
    assert detail["primary_diagnosis"]["description"] == "B"
    assert detail["counts"]["conditions"] == 2


async def test_set_primary_via_patch_and_false_is_rejected(api, pid):
    a = (await _cond(api, pid, is_primary=True, description="A")).json()
    b = (await _cond(api, pid, description="B")).json()
    r = await api.patch(f"/patients/{pid}/conditions/{b['id']}", json={"is_primary": True})
    assert r.status_code == 200 and r.json()["is_primary"] is True
    assert (await api.get(f"/patients/{pid}/conditions")).json()["items"][0]["id"] == b["id"]   # primary first
    assert (await api.patch(f"/patients/{pid}/conditions/{a['id']}", json={"is_primary": False})).status_code == 422
    assert (await api.patch(f"/patients/{pid}/conditions/{a['id']}", json={})).status_code == 422


async def test_resolve_primary_reports_cleared_and_reactivate(api, pid):
    a = (await _cond(api, pid, is_primary=True)).json()
    r = await api.patch(f"/patients/{pid}/conditions/{a['id']}", json={"status": "resolved"})
    body = r.json()
    assert body["status"] == "resolved" and body["resolved_date"] == "2026-11-11"
    assert body["is_primary"] is False and body["primary_cleared"] is True
    again = await api.patch(f"/patients/{pid}/conditions/{a['id']}", json={"is_primary": True})
    assert again.status_code == 409 and again.json()["error"]["code"] == "CONDITION_NOT_ACTIVE"
    back = await api.patch(f"/patients/{pid}/conditions/{a['id']}", json={"status": "active"})
    assert back.json()["resolved_date"] is None and back.json()["primary_cleared"] is False
    both = await api.patch(f"/patients/{pid}/conditions/{a['id']}", json={"status": "resolved"})
    both = await api.patch(f"/patients/{pid}/conditions/{a['id']}", json={"status": "active", "is_primary": True})
    assert both.status_code == 200 and both.json()["is_primary"] is True


async def test_condition_filters_delete_and_other_patients_condition_404(api, pid, make_patient):
    a = (await _cond(api, pid, description="A")).json()
    b = (await _cond(api, pid, description="B")).json()
    await api.patch(f"/patients/{pid}/conditions/{b['id']}", json={"status": "resolved"})
    assert len((await api.get(f"/patients/{pid}/conditions", params={"status": "active"})).json()["items"]) == 1
    assert len((await api.get(f"/patients/{pid}/conditions")).json()["items"]) == 2
    other = (await make_patient(first_name="Z"))["id"]
    assert (await api.patch(f"/patients/{other}/conditions/{a['id']}", json={"status": "resolved"})).status_code == 404
    assert (await api.delete(f"/patients/{pid}/conditions/{a['id']}")).status_code == 204
    assert len((await api.get(f"/patients/{pid}/conditions")).json()["items"]) == 1
    assert (await api.get("/patients/00000000-0000-0000-0000-000000000000/conditions")).status_code == 404


async def test_concurrent_set_primary_leaves_exactly_one(api, pid):
    ids = [(await _cond(api, pid, description=f"C{i}")).json()["id"] for i in range(4)]
    results = await asyncio.gather(*[api.patch(f"/patients/{pid}/conditions/{i}", json={"is_primary": True})
                                     for i in ids])
    assert all(r.status_code == 200 for r in results)
    items = (await api.get(f"/patients/{pid}/conditions")).json()["items"]
    assert sum(i["is_primary"] for i in items) == 1


# ---------------------------------- medications ---------------------------------------------------
async def _med(api, pid, **kw):
    body = {"name": "Losartan", "dose": "50 mg", "route": "oral", "frequency": "Once daily", **kw}
    return await api.post(f"/patients/{pid}/medications", json=body)


async def test_medication_defaults_and_validation(api, pid):
    r = await _med(api, pid)
    assert r.status_code == 201 and r.json()["start_date"] == "2026-11-11" and r.json()["status"] == "active"
    assert (await _med(api, pid, route="rectal")).status_code == 422
    assert (await _med(api, pid, name="")).status_code == 422
    assert (await _med(api, pid, start_date="2026-01-10", end_date="2026-01-01")).status_code == 422


async def test_discontinue_sets_today_once_and_all_filter(api, pid):
    m = (await _med(api, pid)).json()
    r = await api.patch(f"/patients/{pid}/medications/{m['id']}", json={"action": "discontinue"})
    assert r.json()["status"] == "discontinued" and r.json()["end_date"] == "2026-11-11"
    twice = await api.patch(f"/patients/{pid}/medications/{m['id']}", json={"action": "discontinue"})
    assert twice.status_code == 409 and twice.json()["error"]["code"] == "MEDICATION_ALREADY_DISCONTINUED"
    edit = await api.patch(f"/patients/{pid}/medications/{m['id']}", json={"dose": "100 mg"})
    assert edit.status_code == 409
    assert (await api.get(f"/patients/{pid}/medications")).json()["items"] == []
    assert len((await api.get(f"/patients/{pid}/medications", params={"status": "all"})).json()["items"]) == 1


async def test_discontinue_keeps_an_earlier_end_date_and_edits_fields(api, pid):
    m = (await _med(api, pid, start_date="2026-01-01", end_date="2026-02-01")).json()
    edit = await api.patch(f"/patients/{pid}/medications/{m['id']}", json={"dose": "100 mg", "route": "iv"})
    assert edit.json()["dose"] == "100 mg" and edit.json()["route"] == "iv"
    r = await api.patch(f"/patients/{pid}/medications/{m['id']}", json={"action": "discontinue"})
    assert r.json()["end_date"] == "2026-02-01"


async def test_active_medication_with_past_end_date_is_allowed(api, pid):
    r = await _med(api, pid, start_date="2026-01-01", end_date="2026-03-01")
    assert r.status_code == 201 and r.json()["status"] == "active"          # a real data-quality state (§9.3)


# ---------------------------------- allergies -----------------------------------------------------
async def _allergy(api, pid, allergen="Penicillin", **kw):
    return await api.post(f"/patients/{pid}/allergies", json={"allergen": allergen, "severity": "moderate", **kw})


async def test_add_allergy_sets_status_and_bumps_version(api, pid):
    r = await _allergy(api, pid)
    assert r.status_code == 201
    assert r.json()["allergy_status"] == "has_allergies" and r.json()["patient_version"] == 2
    second = await _allergy(api, pid, "Latex", severity="severe")
    assert second.json()["patient_version"] == 2                           # status did not change again
    detail = (await api.get(f"/patients/{pid}")).json()
    assert [a["allergen"] for a in detail["allergy_summary"]] == ["Latex", "Penicillin"]
    assert (await api.get(f"/patients/{pid}/allergies")).json()["allergy_status"] == "has_allergies"


async def test_duplicate_allergen_is_409_case_insensitive(api, pid):
    await _allergy(api, pid, "Penicillin")
    r = await _allergy(api, pid, " penicillin ")
    assert r.status_code == 409 and r.json()["error"]["code"] == "DUPLICATE_ALLERGY"


async def test_remove_last_allergy_returns_to_unknown(api, pid):
    a = (await _allergy(api, pid, "A")).json()["allergy"]["id"]
    b = (await _allergy(api, pid, "B")).json()["allergy"]["id"]
    first = await api.delete(f"/patients/{pid}/allergies/{a}")
    assert first.json()["allergy_status"] == "has_allergies"
    last = await api.delete(f"/patients/{pid}/allergies/{b}")
    assert last.status_code == 200 and last.json()["allergy_status"] == "unknown"
    assert (await api.delete(f"/patients/{pid}/allergies/{b}")).status_code == 404
    again = await _allergy(api, pid, "A")                                   # a removed allergen can be re-added
    assert again.status_code == 201


async def test_nka_rules_with_allergies(api, pid):
    await _allergy(api, pid)
    version = (await api.get(f"/patients/{pid}")).json()["version"]
    r = await api.patch(f"/patients/{pid}", json={"version": version, "allergy_status": "nka"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "ALLERGIES_PRESENT"


async def test_unauthenticated_sub_resources(client, pid=None):
    for path in ("conditions", "medications", "allergies"):
        r = await client.get(f"/patients/00000000-0000-0000-0000-000000000000/{path}")
        assert r.status_code == 401
