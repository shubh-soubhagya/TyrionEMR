"""Patients module (LLD §25.2 Patients / Optimistic lock)."""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.api


async def test_create_assigns_sequential_mrn_and_location(api, make_patient):
    first = await make_patient()
    r = await api.post("/patients", json={"first_name": "Sunita", "last_name": "Verma",
                                          "date_of_birth": "1970-02-02", "sex": "F"})
    assert first["mrn"] == "PT-000101" and r.json()["mrn"] == "PT-000102"
    assert r.headers["location"] == f"/patients/{r.json()['id']}"
    assert first["version"] == 1 and first["allergy_status"] == "unknown" and first["age"] == 67
    assert first["counts"] == {"conditions": 0, "active_conditions": 0, "active_medications": 0, "encounters": 0}


async def test_create_validation_messages(api):
    r = await api.post("/patients", json={"first_name": " ", "last_name": "X", "date_of_birth": "2999-01-01",
                                          "sex": "Q", "phone": "abc", "email": "nope"})
    assert r.status_code == 422
    issues = {d["field"]: d["issue"] for d in r.json()["error"]["details"]}
    assert issues["first_name"] == "First name is required."
    assert issues["phone"] == "Use digits, spaces and + only (7 to 20 characters)."
    assert issues["email"] == "Enter a valid email address."
    assert "sex" in issues


@pytest.mark.parametrize("dob,message", [
    ("2026-11-12", "Date of birth cannot be in the future."),     # tomorrow in IST
    ("1900-01-02", "Check the date of birth. Age would exceed 120."),
])
async def test_dob_rules(api, dob, message):
    r = await api.post("/patients", json={"first_name": "A", "last_name": "B", "date_of_birth": dob, "sex": "M"})
    assert r.status_code == 422
    assert r.json()["error"]["details"][0] == {"field": "date_of_birth", "issue": message}


async def test_dob_today_in_clinic_tz_is_accepted(api):
    r = await api.post("/patients", json={"first_name": "A", "last_name": "B", "date_of_birth": "2026-11-11",
                                          "sex": "F"})
    assert r.status_code == 201 and r.json()["age"] == 0


async def test_unknown_and_readonly_fields_rejected(api):
    r = await api.post("/patients", json={"first_name": "A", "last_name": "B", "date_of_birth": "1980-01-01",
                                          "sex": "M", "mrn": "PT-999999", "established_ckd_stage": "G3a"})
    assert r.status_code == 422


async def test_get_and_404s(api, make_patient):
    p = await make_patient()
    assert (await api.get(f"/patients/{p['id']}")).json()["mrn"] == p["mrn"]
    assert (await api.get("/patients/00000000-0000-0000-0000-000000000000")).status_code == 404
    assert (await api.get("/patients/not-a-uuid")).status_code == 422


async def test_patch_bumps_version_and_stale_version_conflicts(api, make_patient):
    p = await make_patient()
    r = await api.patch(f"/patients/{p['id']}", json={"version": 1, "phone": "+91 9000000000",
                                                      "established_ckd_stage": "G4"})
    assert r.status_code == 200 and r.json()["version"] == 2 and r.json()["established_ckd_stage"] == "G4"
    stale = await api.patch(f"/patients/{p['id']}", json={"version": 1, "phone": "+91 9111111111"})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "VERSION_CONFLICT"


async def test_patch_null_clears_optional_but_not_required(api, make_patient):
    p = await make_patient(phone="+91 9876543210")
    r = await api.patch(f"/patients/{p['id']}", json={"version": 1, "phone": None})
    assert r.status_code == 200 and r.json()["phone"] is None
    bad = await api.patch(f"/patients/{p['id']}", json={"version": 2, "first_name": None})
    assert bad.status_code == 422


async def test_patch_rejects_mrn_and_has_allergies(api, make_patient):
    p = await make_patient()
    assert (await api.patch(f"/patients/{p['id']}", json={"version": 1, "mrn": "PT-1"})).status_code == 422
    assert (await api.patch(f"/patients/{p['id']}", json={"version": 1, "allergy_status": "has_allergies"})
            ).status_code == 422
    ok = await api.patch(f"/patients/{p['id']}", json={"version": 1, "allergy_status": "nka"})
    assert ok.status_code == 200 and ok.json()["allergy_status"] == "nka"


async def test_soft_delete_hides_everywhere(api, make_patient):
    p = await make_patient()
    assert (await api.delete(f"/patients/{p['id']}")).status_code == 204
    assert (await api.get(f"/patients/{p['id']}")).status_code == 404
    assert (await api.patch(f"/patients/{p['id']}", json={"version": 1, "phone": None})).status_code == 404
    assert (await api.delete(f"/patients/{p['id']}")).status_code == 404
    assert (await api.get("/patients")).json()["total"] == 0


async def test_requires_auth_and_clinician(client, sign):
    assert (await client.get("/patients")).status_code == 401
    r = await client.get("/patients", headers={"Authorization": f"Bearer {sign(role='nurse')}"})
    assert r.status_code == 403


async def test_concurrent_stale_patch_one_wins(api, make_patient):
    p = await make_patient()
    results = await asyncio.gather(*[api.patch(f"/patients/{p['id']}", json={"version": 1, "address": f"a{i}"})
                                     for i in range(2)])
    assert sorted(r.status_code for r in results) == [200, 409]


async def test_twenty_concurrent_registrations_distinct_mrns(api):
    body = {"first_name": "A", "last_name": "B", "date_of_birth": "1980-01-01", "sex": "M"}
    results = await asyncio.gather(*[api.post("/patients", json=body) for _ in range(20)])
    assert all(r.status_code == 201 for r in results)
    assert len({r.json()["mrn"] for r in results}) == 20


# ---------------- list / search / sort ----------------------------------------------------------
@pytest.fixture
async def roster(make_patient):
    people = [("Ramesh", "Kulkarni", "1959-04-17", "M"), ("Sunita", "Verma", "1971-01-05", "F"),
              ("Arjun", "Mehta", "1985-07-30", "M"), ("Fatima", "Sheikh", "1948-12-01", "F")]
    return [await make_patient(first_name=f, last_name=ln, date_of_birth=d, sex=s) for f, ln, d, s in people]


async def test_list_default_sort_name_and_shape(api, roster):
    r = (await api.get("/patients")).json()
    assert [i["last_name"] for i in r["items"]] == ["Kulkarni", "Mehta", "Sheikh", "Verma"]
    assert r["total"] == 4 and r["page"] == 1 and r["size"] == 20
    assert r["items"][0]["primary_diagnosis"] is None and r["items"][0]["last_visit"] is None


async def test_list_sort_keys_and_directions(api, roster):
    async def order(**params):
        return [i["last_name"] for i in (await api.get("/patients", params=params)).json()["items"]]

    assert await order(sort="name", dir="desc") == ["Verma", "Sheikh", "Mehta", "Kulkarni"]
    assert await order(sort="mrn") == ["Kulkarni", "Verma", "Mehta", "Sheikh"]
    assert await order(sort="age") == ["Mehta", "Verma", "Kulkarni", "Sheikh"]          # youngest first
    assert await order(sort="age", dir="desc") == ["Sheikh", "Kulkarni", "Verma", "Mehta"]
    assert len(await order(sort="dx")) == 4 and len(await order(sort="visit")) == 4
    assert (await api.get("/patients", params={"sort": "egfr"})).status_code == 422


async def test_list_filters(api, roster):
    assert (await api.get("/patients", params={"sex": "F"})).json()["total"] == 2
    await api.patch(f"/patients/{roster[0]['id']}", json={"version": 1, "established_ckd_stage": "G3b"})
    assert (await api.get("/patients", params={"stage": "G3b"})).json()["total"] == 1
    assert (await api.get("/patients", params={"stage": "none"})).json()["total"] == 3
    ids = f"{roster[1]['id']},{roster[2]['id']}"
    assert (await api.get("/patients", params={"ids": ids})).json()["total"] == 2
    assert (await api.get("/patients", params={"ids": "garbage"})).status_code == 422
    too_many = ",".join(["00000000-0000-0000-0000-000000000000"] * 501)
    assert (await api.get("/patients", params={"ids": too_many})).status_code == 422


@pytest.mark.parametrize("q,expected", [
    ("kulkarni", ["Kulkarni"]), ("Kulkarni Ramesh", ["Kulkarni"]), ("ramesh kul", ["Kulkarni"]),
    ("PT-000102", ["Verma"]), ("pt102", ["Verma"]), ("102", ["Verma"]),
    ("PT-0001", ["Kulkarni", "Mehta", "Sheikh", "Verma"]),
    ("zzz", []), ("100%", []), ("_", []), ("\\", []),
])
async def test_search(api, roster, q, expected):
    items = (await api.get("/patients", params={"q": q})).json()["items"]
    assert sorted(i["last_name"] for i in items) == sorted(expected)


async def test_paging_is_stable_and_total_survives_past_end(api, roster):
    p1 = (await api.get("/patients", params={"size": 3, "page": 1})).json()
    p2 = (await api.get("/patients", params={"size": 3, "page": 2})).json()
    assert [len(p1["items"]), len(p2["items"]), p1["total"], p2["total"]] == [3, 1, 4, 4]
    assert not {i["id"] for i in p1["items"]} & {i["id"] for i in p2["items"]}
    past = (await api.get("/patients", params={"size": 3, "page": 9})).json()
    assert past["items"] == [] and past["total"] == 4
    assert (await api.get("/patients", params={"size": 101})).status_code == 422


async def test_list_accepts_the_maximum_500_ids(api):
    """The gateway forwards up to 32 KiB of request line; 500 UUIDs are about 18.5 KB (G8, ADR-020)."""
    ids = ",".join(str(uuid.uuid4()) for _ in range(500))
    resp = await api.get("/patients", params={"ids": ids})
    assert resp.status_code == 200 and resp.json()["total"] == 0


def test_the_server_is_started_with_a_32_kib_h11_limit():
    """The in-process client has no h11 layer, so the limit itself is checked where it is set (README: manual check)."""
    root = Path(__file__).resolve().parents[2]
    for rel in ("scripts/entrypoint.sh", "Makefile"):
        assert "--h11-max-incomplete-event-size 32768" in (root / rel).read_text(encoding="utf-8"), rel


async def test_a_trailing_slash_is_a_404_not_a_redirect(api):
    resp = await api.get("/patients/", follow_redirects=False)
    assert resp.status_code == 404
