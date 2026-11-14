"""Migration 0004: the two sort columns are backfilled from existing rows, the indexes exist, and the downgrade
removes everything. Uses the real test database and always ends at head."""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.conftest import ROOT

pytestmark = pytest.mark.api


def alembic(url: str, *args: str) -> None:
    subprocess.run([sys.executable, "-m", "alembic", *args], cwd=ROOT, check=True, capture_output=True,
                   env={**os.environ, "PATIENT_DATABASE_URL": url})


async def test_backfill_indexes_and_round_trip(db_engine, migrated_db):
    url = migrated_db
    await db_engine.dispose()
    alembic(url, "downgrade", "0003")
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            cols = {r[0] for r in await conn.execute(text(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'patients'"))}
            assert not {"last_visit", "primary_dx_sort"} & cols                    # the downgrade removed both
            pid = (await conn.execute(text(
                "INSERT INTO patients (first_name,last_name,date_of_birth,sex) "
                "VALUES ('A','B','1970-01-01','M') RETURNING id"))).scalar_one()
            await conn.execute(text(
                "INSERT INTO patient_conditions (patient_id, description, category, is_primary) "
                "VALUES (:p, 'Diabetic Nephropathy', 'nephrology', true)"), {"p": pid})
            ins = ("INSERT INTO encounters (patient_id,encounter_date,clinician_id,clinician_name,created_by,"
                   "chief_complaint,assessment,plan) VALUES (:p, :d, gen_random_uuid(), 'Dr', gen_random_uuid(),"
                   "'c','a','p') RETURNING id")
            for day in ("2026-03-01", "2026-05-01"):
                when = datetime.fromisoformat(f"{day}T09:00:00+00:00")
                eid = (await conn.execute(text(ins), {"p": pid, "d": when})).scalar_one()
                await conn.execute(text("UPDATE encounters SET status='final', finalized_at=now() WHERE id=:e"),
                                   {"e": eid})
            draft_at = datetime.fromisoformat("2026-06-01T09:00:00+00:00")
            await conn.execute(text(ins), {"p": pid, "d": draft_at})                        # a draft: not a visit
        await engine.dispose()

        alembic(url, "upgrade", "head")
        engine = create_async_engine(url)
        async with engine.connect() as conn:
            row = (await conn.execute(text("SELECT last_visit, primary_dx_sort FROM patients"))).one()
            idx = {r[0] for r in await conn.execute(text(
                "SELECT indexname FROM pg_indexes WHERE tablename = 'patients'"))}
        assert row.last_visit.isoformat().startswith("2026-05-01T09:00:00")
        assert row.primary_dx_sort == "diabetic nephropathy"
        assert {"patients_last_visit", "patients_primary_dx_sort"} <= idx
    finally:
        await engine.dispose()
        alembic(url, "upgrade", "head")
