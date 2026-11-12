"""GET /encounters dashboard modes (LLD §12.1, §25.2 Dashboard). "Today" is 2026-11-11 in CLINIC_TZ."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.api


def body(**kw):
    base = {"encounter_date": "2026-10-01T10:00:00+05:30", "chief_complaint": "cc", "assessment": "a", "plan": "p",
            "status": "final"}
    base.update(kw)
    return base


async def enc(api, pid, **kw):
    r = await api.post(f"/patients/{pid}/encounters", json=body(**kw))
    assert r.status_code == 201, r.text
    return r.json()["encounter"]


async def test_exactly_one_mode(api):
    assert (await api.get("/encounters")).status_code == 422
    both = await api.get("/encounters", params={"status": "draft", "upcoming_followups": "true"})
    assert both.status_code == 422
    assert (await api.get("/encounters", params={"status": "final"})).status_code == 422
    assert (await api.get("/encounters", params={"status": "draft", "limit": 0})).status_code == 422


async def test_requires_auth(client):
    assert (await client.get("/encounters", params={"status": "draft"})).status_code == 401


async def test_drafts_mode_total_order_and_deleted_patients(api, make_patient):
    a = (await make_patient(first_name="Ramesh", last_name="Kulkarni"))["id"]
    b = (await make_patient(first_name="Sunita", last_name="Verma"))["id"]
    old = await enc(api, a, status="draft", encounter_date="2026-10-01T10:00:00+05:30", chief_complaint="old")
    new = await enc(api, b, status="draft", encounter_date="2026-11-05T10:00:00+05:30", chief_complaint="new")
    await enc(api, a)                                                                   # final: not a draft
    r = (await api.get("/encounters", params={"status": "draft", "limit": 1})).json()
    assert r["total"] == 2 and [i["encounter_id"] for i in r["items"]] == [new["id"]]   # newest first, limit applied
    full = (await api.get("/encounters", params={"status": "draft"})).json()
    assert [i["encounter_id"] for i in full["items"]] == [new["id"], old["id"]]
    item = full["items"][0]
    assert item["mrn"] == "PT-000102" and item["patient_name"] == "Sunita Verma" and item["patient_id"] == b
    await api.delete(f"/patients/{b}")
    after = (await api.get("/encounters", params={"status": "draft"})).json()
    assert after["total"] == 1 and after["items"][0]["encounter_id"] == old["id"]


async def test_deleted_draft_is_not_listed(api, make_patient):
    pid = (await make_patient())["id"]
    d = await enc(api, pid, status="draft")
    await api.delete(f"/patients/{pid}/encounters/{d['id']}")
    assert (await api.get("/encounters", params={"status": "draft"})).json() == {"items": [], "total": 0}


async def test_followups_take_only_the_latest_final_encounter(api, make_patient):
    a = (await make_patient(first_name="Ramesh", last_name="Kulkarni"))["id"]
    b = (await make_patient(first_name="Sunita", last_name="Verma"))["id"]
    c = (await make_patient(first_name="Arjun", last_name="Mehta"))["id"]
    # a: an older visit promised a future follow-up, but a NEWER visit replaced it with none -> excluded
    await enc(api, a, encounter_date="2026-10-01T10:00:00+05:30", follow_up_date="2026-12-01")
    await enc(api, a, encounter_date="2026-10-20T10:00:00+05:30")
    # b: latest final has a future follow-up -> included
    await enc(api, b, encounter_date="2026-10-15T10:00:00+05:30", follow_up_date="2026-12-23")
    # c: follow-up today is included; a past follow-up is not
    cc = await enc(api, c, encounter_date="2026-10-10T10:00:00+05:30", follow_up_date="2026-11-11")
    r = (await api.get("/encounters", params={"upcoming_followups": "true"})).json()
    assert [i["patient_name"] for i in r["items"]] == ["Arjun Mehta", "Sunita Verma"]       # soonest first
    assert r["total"] == 2 and r["items"][0]["encounter_id"] == cc["id"]
    assert r["items"][1]["follow_up_date"] == "2026-12-23"


async def test_followups_exclude_past_drafts_and_deleted_patients_and_apply_limit(api, make_patient):
    ids = [(await make_patient(first_name=f"P{i}", last_name="Z"))["id"] for i in range(3)]
    for i, pid in enumerate(ids):
        await enc(api, pid, follow_up_date=f"2026-12-0{i + 1}")
    await enc(api, ids[0], status="draft", follow_up_date="2026-11-20")                  # drafts never count
    past = (await make_patient(first_name="Past", last_name="Z"))["id"]
    await enc(api, past, follow_up_date="2026-11-10", encounter_date="2026-10-01T10:00:00+05:30")
    limited = (await api.get("/encounters", params={"upcoming_followups": "true", "limit": 2})).json()
    assert limited["total"] == 3 and [i["follow_up_date"] for i in limited["items"]] == ["2026-12-01", "2026-12-02"]
    await api.delete(f"/patients/{ids[0]}")
    after = (await api.get("/encounters", params={"upcoming_followups": "true"})).json()
    assert after["total"] == 2
