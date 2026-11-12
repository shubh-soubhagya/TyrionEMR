"""LLD §25.3: the database itself protects the medical-record invariants (raw SQL, no service code)."""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.dberrors import sqlstate_of

pytestmark = pytest.mark.api

PATIENT = ("INSERT INTO patients (first_name,last_name,date_of_birth,sex) "
           "VALUES ('A','B','1970-01-01','M') RETURNING id")
ENC = ("INSERT INTO encounters (patient_id,encounter_date,clinician_id,clinician_name,created_by,chief_complaint,"
       "assessment,plan,status,finalized_at) VALUES (:p, now(), gen_random_uuid(), 'Dr X', gen_random_uuid(), "
       "'c','a','p','final', now()) RETURNING id")
DRAFT = ("INSERT INTO encounters (patient_id,encounter_date,clinician_id,clinician_name,created_by) "
         "VALUES (:p, now(), gen_random_uuid(), 'Dr X', gen_random_uuid()) RETURNING id")


async def _patient(conn) -> str:
    return (await conn.execute(text(PATIENT))).scalar_one()


async def test_mrn_comes_from_sequence(db_engine):
    async with db_engine.begin() as conn:
        a = (await conn.execute(text("INSERT INTO patients (first_name,last_name,date_of_birth,sex) "
                                     "VALUES ('A','B','1970-01-01','M') RETURNING mrn"))).scalar_one()
        b = (await conn.execute(text("INSERT INTO patients (first_name,last_name,date_of_birth,sex) "
                                     "VALUES ('C','D','1970-01-01','F') RETURNING mrn"))).scalar_one()
    assert (a, b) == ("PT-000101", "PT-000102")


async def test_final_encounter_cannot_be_updated(db_engine):
    async with db_engine.begin() as conn:
        pid = await _patient(conn)
        eid = (await conn.execute(text(ENC), {"p": pid})).scalar_one()
    with pytest.raises(DBAPIError) as exc:
        async with db_engine.begin() as conn:
            await conn.execute(text("UPDATE encounters SET plan='x' WHERE id=:e"), {"e": eid})
    assert "ENCOUNTER_FINAL" in str(exc.value.orig.__cause__.hint)


async def test_children_of_final_encounter_are_frozen(db_engine):
    async with db_engine.begin() as conn:
        pid = await _patient(conn)
        eid = (await conn.execute(text(ENC), {"p": pid})).scalar_one()
    with pytest.raises(DBAPIError):
        async with db_engine.begin() as conn:
            await conn.execute(text("INSERT INTO encounter_vitals (encounter_id, heart_rate) VALUES (:e, 70)"),
                               {"e": eid})
    with pytest.raises(DBAPIError):
        async with db_engine.begin() as conn:
            await conn.execute(text("INSERT INTO encounter_diagnoses (encounter_id,seq,description) "
                                    "VALUES (:e,1,'x')"), {"e": eid})


async def test_draft_can_be_edited_then_finalized(db_engine):
    async with db_engine.begin() as conn:
        pid = await _patient(conn)
        eid = (await conn.execute(text(DRAFT), {"p": pid})).scalar_one()
        await conn.execute(text("INSERT INTO encounter_vitals (encounter_id, heart_rate) VALUES (:e, 70)"), {"e": eid})
        await conn.execute(text("UPDATE encounters SET chief_complaint='c', assessment='a', plan='p' WHERE id=:e"),
                           {"e": eid})
        await conn.execute(text("UPDATE encounters SET status='final', finalized_at=now() WHERE id=:e"), {"e": eid})


async def test_incomplete_final_is_refused_by_check(db_engine):
    with pytest.raises(IntegrityError):
        async with db_engine.begin() as conn:
            pid = await _patient(conn)
            await conn.execute(text(
                "INSERT INTO encounters (patient_id,encounter_date,clinician_id,clinician_name,created_by,status,"
                "finalized_at) VALUES (:p, now(), gen_random_uuid(),'Dr',gen_random_uuid(),'final', now())"),
                {"p": pid})


async def test_encounter_hard_delete_refused(db_engine):
    async with db_engine.begin() as conn:
        pid = await _patient(conn)
        eid = (await conn.execute(text(DRAFT), {"p": pid})).scalar_one()
    with pytest.raises(DBAPIError):
        async with db_engine.begin() as conn:
            await conn.execute(text("DELETE FROM encounters WHERE id=:e"), {"e": eid})


async def test_no_hard_delete_on_patients(db_engine):
    async with db_engine.begin() as conn:
        await _patient(conn)
    with pytest.raises(DBAPIError) as exc:
        async with db_engine.begin() as conn:
            await conn.execute(text("DELETE FROM patients"))
    assert "NO_HARD_DELETE" in str(exc.value.orig.__cause__.hint)


async def test_audit_is_append_only(db_engine):
    async with db_engine.begin() as conn:
        await conn.execute(text("INSERT INTO audit_events (actor_id, action, resource) "
                                "VALUES (gen_random_uuid(), 'patient.view', 'patient')"))
    with pytest.raises(DBAPIError) as exc:
        async with db_engine.begin() as conn:
            await conn.execute(text("UPDATE audit_events SET action='x'"))
    assert "AUDIT_APPEND_ONLY" in str(exc.value.orig.__cause__.hint)


async def test_two_active_primaries_violate_unique_index(db_engine):
    with pytest.raises(IntegrityError) as exc:
        async with db_engine.begin() as conn:
            pid = await _patient(conn)
            for d in ("one", "two"):
                await conn.execute(text(
                    "INSERT INTO patient_conditions (patient_id,description,category,is_primary) "
                    "VALUES (:p,:d,'nephrology',true)"), {"p": pid, "d": d})
    assert sqlstate_of(exc.value) == "23505"


async def test_duplicate_allergen_is_case_insensitive(db_engine):
    with pytest.raises(IntegrityError):
        async with db_engine.begin() as conn:
            pid = await _patient(conn)
            for a in ("Penicillin", " penicillin "):
                await conn.execute(text("INSERT INTO allergies (patient_id, allergen) VALUES (:p,:a)"),
                                   {"p": pid, "a": a})


async def test_vitals_constraints(db_engine):
    async with db_engine.begin() as conn:
        pid = await _patient(conn)
        eid = (await conn.execute(text(DRAFT), {"p": pid})).scalar_one()
    for bad in ("systolic_bp=49", "systolic_bp=120, diastolic_bp=120", ""):
        with pytest.raises(IntegrityError):
            async with db_engine.begin() as conn:
                cols = bad or "heart_rate=NULL"
                names, vals = zip(*(p.split("=") for p in cols.split(", ")), strict=True)
                await conn.execute(text(f"INSERT INTO encounter_vitals (encounter_id,{','.join(names)}) "
                                        f"VALUES (:e,{','.join(vals)})"), {"e": eid})


async def test_patient_checks(db_engine):
    for sql in ("INSERT INTO patients (first_name,last_name,date_of_birth,sex) VALUES ('A','B','1899-12-31','M')",
                "INSERT INTO patients (first_name,last_name,date_of_birth,sex) VALUES ('A','B','1970-01-01','X')",
                "INSERT INTO patients (first_name,last_name,date_of_birth,sex,established_ckd_stage) "
                "VALUES ('A','B','1970-01-01','M','G6')"):
        with pytest.raises(IntegrityError):
            async with db_engine.begin() as conn:
                await conn.execute(text(sql))
