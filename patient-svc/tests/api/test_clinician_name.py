"""Clinician name on encounters: resolved from auth-svc (here a fake), nullable, never inside a transaction."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.api

BODY = {"encounter_date": "2026-11-11T10:00:00+05:30", "chief_complaint": "cc", "assessment": "a", "plan": "p"}


@pytest.fixture
async def pid(make_patient) -> str:
    return (await make_patient())["id"]


async def create(api, pid, **kw):
    return await api.post(f"/patients/{pid}/encounters", json={**BODY, **kw})


async def stored_name(db_engine, eid: str) -> str | None:
    async with db_engine.connect() as conn:
        return (await conn.execute(text("SELECT clinician_name FROM encounters WHERE id = :e"), {"e": eid})).scalar()


async def test_create_stores_the_name_from_the_directory(api, pid, directory):
    r = await create(api, pid)
    assert r.json()["encounter"]["clinician_name"] == "Dr. Test"
    assert len(directory.calls) == 1
    user_id, authorization, request_id = directory.calls[0]
    assert authorization == api.headers["Authorization"] and request_id.startswith("req-")


async def test_directory_down_still_creates_the_encounter_with_a_null_name(api, pid, directory, db_engine):
    directory.default = None
    r = await create(api, pid)
    assert r.status_code == 201 and r.json()["encounter"]["clinician_name"] is None
    assert await stored_name(db_engine, r.json()["encounter"]["id"]) is None
    history = (await api.get(f"/patients/{pid}/encounters")).json()["items"]
    assert history[0]["clinician_name"] is None


async def test_no_unknown_clinician_placeholder_is_ever_stored(api, pid, directory, db_engine):
    directory.default = None
    await create(api, pid)
    async with db_engine.connect() as conn:
        n = (await conn.execute(text("SELECT count(*) FROM encounters WHERE clinician_name = 'Unknown clinician'"))
             ).scalar_one()
    assert n == 0


async def test_later_patch_by_the_same_clinician_fills_a_null_name(api, pid, directory, db_engine):
    directory.default = None
    enc = (await create(api, pid)).json()["encounter"]
    directory.default = "Dr. Back Online"
    r = await api.patch(f"/patients/{pid}/encounters/{enc['id']}", json={"version": 1, "plan": "edited"})
    assert r.status_code == 200 and r.json()["encounter"]["clinician_name"] == "Dr. Back Online"
    assert r.json()["encounter"]["version"] == 2            # one bump for the edit; the name fill adds none
    n = len(directory.calls)
    await api.patch(f"/patients/{pid}/encounters/{enc['id']}", json={"version": 2, "plan": "again"})
    assert len(directory.calls) == n                         # name already set: no lookup at all


async def test_finalize_by_the_same_clinician_fills_the_name_before_the_status_flips(api, pid, directory, db_engine):
    directory.default = None
    enc = (await create(api, pid)).json()["encounter"]
    directory.default = "Dr. Back Online"
    r = await api.post(f"/patients/{pid}/encounters/{enc['id']}/finalize", json={"version": 1})
    assert r.status_code == 200 and r.json()["encounter"]["status"] == "final"
    assert r.json()["encounter"]["clinician_name"] == "Dr. Back Online"
    assert await stored_name(db_engine, enc["id"]) == "Dr. Back Online"


async def test_patch_with_status_final_fills_the_name_too(api, pid, directory):
    directory.default = None
    enc = (await create(api, pid)).json()["encounter"]
    directory.default = "Dr. Back Online"
    r = await api.patch(f"/patients/{pid}/encounters/{enc['id']}", json={"version": 1, "status": "final"})
    assert r.status_code == 200 and r.json()["encounter"]["clinician_name"] == "Dr. Back Online"


async def test_finalize_by_a_different_clinician_never_changes_the_name(api, pid, directory, db_engine, sign):
    directory.default = None
    enc = (await create(api, pid)).json()["encounter"]
    other = str(uuid.uuid4())
    directory.default = "Dr. Someone Else"
    api.headers["Authorization"] = f"Bearer {sign(sub=other)}"
    calls_before = len(directory.calls)
    r = await api.post(f"/patients/{pid}/encounters/{enc['id']}/finalize", json={"version": 1})
    assert r.status_code == 200 and r.json()["encounter"]["clinician_name"] is None
    assert str(r.json()["encounter"]["finalized_by"]) == other           # the finalizer is recorded separately
    assert str(r.json()["encounter"]["clinician_id"]) != other
    assert len(directory.calls) == calls_before                          # not even looked up
    assert await stored_name(db_engine, enc["id"]) is None


async def test_a_final_encounter_with_a_null_name_stays_null(api, pid, directory, db_engine):
    directory.default = None
    enc = (await create(api, pid, status="final")).json()["encounter"]
    assert enc["status"] == "final" and enc["clinician_name"] is None
    directory.default = "Dr. Late"
    assert (await api.patch(f"/patients/{pid}/encounters/{enc['id']}",
                            json={"version": enc["version"], "plan": "x"})).status_code == 409
    assert await stored_name(db_engine, enc["id"]) is None


async def test_no_lookup_ever_happens_inside_a_transaction(api, pid, directory):
    """FakeDirectory asserts that no session is in a transaction at call time; exercise every call site."""
    directory.default = None
    enc = (await create(api, pid)).json()["encounter"]
    directory.default = "Dr. Back Online"
    await api.patch(f"/patients/{pid}/encounters/{enc['id']}", json={"version": 1, "plan": "p2"})
    directory.default = None
    other = (await create(api, pid)).json()["encounter"]
    directory.default = "Dr. Back Online"
    await api.post(f"/patients/{pid}/encounters/{other['id']}/finalize", json={"version": 1})
    await create(api, pid, status="final")
    assert len(directory.calls) >= 5 and directory.sessions
