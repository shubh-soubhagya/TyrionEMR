"""Migration 0003: placeholder names become NULL (even on FINAL encounters), the guard is restored, and the
upgrade/downgrade round-trips. Uses the real test database and always ends at head."""
from __future__ import annotations

import os
import subprocess
import sys

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from tests.conftest import ROOT

pytestmark = pytest.mark.api

PLACEHOLDER = "Unknown clinician"


def alembic(url: str, *args: str) -> None:
    subprocess.run([sys.executable, "-m", "alembic", *args], cwd=ROOT, check=True, capture_output=True,
                   env={**os.environ, "PATIENT_DATABASE_URL": url})


async def test_backfill_guard_and_round_trip(db_engine, migrated_db):
    url = migrated_db
    await db_engine.dispose()
    alembic(url, "downgrade", "0002")
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:                      # state as it was before 0003
            pid = (await conn.execute(text(
                "INSERT INTO patients (first_name,last_name,date_of_birth,sex) "
                "VALUES ('A','B','1970-01-01','M') RETURNING id"))).scalar_one()
            ins = ("INSERT INTO encounters (patient_id,encounter_date,clinician_id,clinician_name,created_by,"
                   "chief_complaint,assessment,plan) VALUES (:p, now(), gen_random_uuid(), :n, gen_random_uuid(),"
                   "'c','a','p') RETURNING id")
            final_id = (await conn.execute(text(ins), {"p": pid, "n": PLACEHOLDER})).scalar_one()
            await conn.execute(text("UPDATE encounters SET status='final', finalized_at=now() WHERE id=:e"),
                               {"e": final_id})
            await conn.execute(text(ins), {"p": pid, "n": PLACEHOLDER})           # a draft with the placeholder
            await conn.execute(text(ins), {"p": pid, "n": "Dr Real"})
            before = (await conn.execute(text(
                "SELECT max(updated_at) FROM encounters WHERE clinician_name = :n"), {"n": PLACEHOLDER})).scalar_one()
        # NOT NULL still enforced at 0002
        with pytest.raises(DBAPIError):
            async with engine.begin() as conn:
                await conn.execute(text("UPDATE encounters SET clinician_name = NULL WHERE clinician_name = 'Dr Real'"))

        await engine.dispose()
        alembic(url, "upgrade", "head")
        engine = create_async_engine(url)

        async with engine.connect() as conn:
            rows = (await conn.execute(text(
                "SELECT status, clinician_name, updated_at FROM encounters ORDER BY created_at, id"))).all()
        by_status = sorted(((r.status, r.clinician_name) for r in rows), key=str)
        expected = [("draft", "Dr Real"), ("draft", None), ("final", None)]            # placeholders -> NULL
        assert by_status == sorted(expected, key=str)
        assert max(r.updated_at for r in rows if r.clinician_name is None) == before   # timestamps untouched
        # the guard is back on: a final encounter can no longer be modified
        with pytest.raises(DBAPIError) as exc:
            async with engine.begin() as conn:
                await conn.execute(text("UPDATE encounters SET plan='x' WHERE status='final'"))
        assert "ENCOUNTER_FINAL" in str(exc.value.orig.__cause__.hint)

        # set_updated_at(): an explicit updated_at is honoured, otherwise now() is used
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE patients SET updated_at = TIMESTAMPTZ '2020-01-01 00:00+00'"))
            kept = (await conn.execute(text("SELECT updated_at FROM patients"))).scalar_one()
            await conn.execute(text("UPDATE patients SET phone = '+91 9000000001'"))
            bumped = (await conn.execute(text("SELECT updated_at FROM patients"))).scalar_one()
        assert kept.year == 2020 and bumped.year >= 2026

        # downgrade then upgrade again: placeholders come back, NOT NULL is restored, then NULLs return
        await engine.dispose()
        alembic(url, "downgrade", "0002")
        engine = create_async_engine(url)
        async with engine.connect() as conn:
            names = sorted(r[0] for r in await conn.execute(text("SELECT clinician_name FROM encounters")))
        assert names == ["Dr Real", PLACEHOLDER, PLACEHOLDER]
    finally:
        await engine.dispose()
        alembic(url, "upgrade", "head")
    check = create_async_engine(url)
    try:
        async with check.connect() as conn:
            head = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar_one()
            nullable = (await conn.execute(text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_name='encounters' AND column_name='clinician_name'"))).scalar_one()
        assert head == "0003" and nullable == "YES"
    finally:
        await check.dispose()
