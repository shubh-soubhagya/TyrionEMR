"""patients.last_visit and patients.primary_dx_sort (migration 0004, README D11): derived list-sort keys kept in the
writing transaction. They must always equal what the lateral joins compute, and must never bump `version`."""
from __future__ import annotations

import pytest
from sqlalchemy import text

from app.cli.seed_patients import seed_scenarios
from app.db.session import create_sessionmaker
from tests.api.test_encounters import create
from tests.conftest import make_settings

pytestmark = pytest.mark.api

CONSISTENCY = text("""
    SELECT p.id FROM patients p
    LEFT JOIN LATERAL (SELECT max(e.encounter_date) AS v FROM encounters e
                       WHERE e.patient_id = p.id AND e.status = 'final' AND e.deleted_at IS NULL) lv ON true
    LEFT JOIN LATERAL (SELECT lower(c.description) AS v FROM patient_conditions c
                       WHERE c.patient_id = p.id AND c.is_primary AND c.status = 'active'
                         AND c.deleted_at IS NULL LIMIT 1) pc ON true
    WHERE p.last_visit IS DISTINCT FROM lv.v OR p.primary_dx_sort IS DISTINCT FROM pc.v""")


async def inconsistent(db_engine) -> list:
    async with db_engine.connect() as conn:
        return list((await conn.execute(CONSISTENCY)).scalars())


async def keys(db_engine, pid: str):
    async with db_engine.connect() as conn:
        row = (await conn.execute(text("SELECT last_visit, primary_dx_sort, version FROM patients WHERE id = :p"),
                                  {"p": pid})).one()
    return row.last_visit, row.primary_dx_sort, row.version


async def cond(api, pid, description, **kw):
    r = await api.post(f"/patients/{pid}/conditions", json={"description": description, "category": "nephrology", **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_columns_follow_every_change_and_match_the_lateral_joins(api, make_patient, db_engine):
    pid = (await make_patient())["id"]
    assert await keys(db_engine, pid) == (None, None, 1)

    a = await cond(api, pid, "Diabetic Nephropathy", is_primary=True)
    b = await cond(api, pid, "Hypertensive CKD")
    assert (await keys(db_engine, pid))[1] == "diabetic nephropathy"
    await api.patch(f"/patients/{pid}/conditions/{b}", json={"is_primary": True})          # set primary
    assert (await keys(db_engine, pid))[1] == "hypertensive ckd"
    await api.patch(f"/patients/{pid}/conditions/{b}", json={"status": "resolved"})         # resolve: no primary left
    assert (await keys(db_engine, pid))[1] is None
    await api.patch(f"/patients/{pid}/conditions/{a}", json={"is_primary": True})
    await api.patch(f"/patients/{pid}/conditions/{a}", json={"description": "IgA Nephropathy"})   # rename the primary
    assert (await keys(db_engine, pid))[1] == "iga nephropathy"
    await api.patch(f"/patients/{pid}/conditions/{b}", json={"status": "active"})           # reactivate (not primary)
    assert (await keys(db_engine, pid))[1] == "iga nephropathy"
    assert (await api.delete(f"/patients/{pid}/conditions/{a}")).status_code in (200, 204)  # delete the primary
    assert (await keys(db_engine, pid))[1] is None

    # two final encounters out of date order, then a draft that is deleted
    late = await create(api, pid, status="final", encounter_date="2026-11-10T09:00:00+05:30", diagnoses=[])
    assert late.status_code == 201, late.text
    early = await create(api, pid, status="final", encounter_date="2026-09-01T09:00:00+05:30", diagnoses=[])
    assert early.status_code == 201, early.text
    last, _, _ = await keys(db_engine, pid)
    assert last.isoformat().startswith("2026-11-10T03:30:00")                               # the later one stays
    draft = (await create(api, pid, encounter_date="2026-11-11T09:00:00+05:30", diagnoses=[])).json()["encounter"]
    assert (await keys(db_engine, pid))[0] == last                                          # drafts do not count
    assert (await api.delete(f"/patients/{pid}/encounters/{draft['id']}")).status_code in (200, 204)
    assert (await keys(db_engine, pid))[0] == last
    assert await inconsistent(db_engine) == []


async def test_derived_columns_never_bump_the_patient_version(api, make_patient, db_engine):
    pid = (await make_patient())["id"]
    await cond(api, pid, "Primary one", is_primary=True)
    assert (await keys(db_engine, pid))[2] == 1                                             # set primary: no bump
    r = await create(api, pid, status="final", diagnoses=[])
    assert r.status_code == 201, r.text
    last, dx, version = await keys(db_engine, pid)
    assert last is not None and dx == "primary one" and version == 1                        # finalize: no bump
    # a clinician editing demographics with the version they read still succeeds
    ok = await api.patch(f"/patients/{pid}", json={"version": 1, "phone": "9876543210"})
    assert ok.status_code == 200, ok.text


async def test_list_sorts_use_the_columns_and_keep_the_response_shape(api, make_patient):
    p1, p2, p3 = [(await make_patient(first_name=n))["id"] for n in ("A", "B", "C")]
    await cond(api, p1, "Zeta disease", is_primary=True)
    await cond(api, p2, "Alpha disease", is_primary=True)
    await create(api, p1, status="final", encounter_date="2026-10-01T09:00:00+05:30", diagnoses=[])
    await create(api, p2, status="final", encounter_date="2026-11-01T09:00:00+05:30", diagnoses=[])
    by_dx = (await api.get("/patients", params={"sort": "dx"})).json()["items"]
    assert [i["id"] for i in by_dx] == [p2, p1, p3]                                         # no primary sorts last
    assert by_dx[0]["primary_diagnosis"]["description"] == "Alpha disease"                  # displayed value unchanged
    by_visit = (await api.get("/patients", params={"sort": "visit"})).json()["items"]       # newest first by default
    assert [i["id"] for i in by_visit] == [p2, p1, p3]
    assert by_visit[0]["last_visit"] is not None and by_visit[2]["last_visit"] is None


async def test_the_seed_leaves_both_columns_consistent(db_engine, clock):
    await seed_scenarios(create_sessionmaker(db_engine), make_settings(), clock)
    assert await inconsistent(db_engine) == []
    async with db_engine.connect() as conn:
        n = (await conn.execute(text("SELECT count(*) FROM patients WHERE last_visit IS NOT NULL"))).scalar_one()
    assert n > 0
