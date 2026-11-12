"""Database-level guarantees (HLD §5.4): append-only results, plausibility CHECKs, isolation."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.dberrors import map_db_error

pytestmark = pytest.mark.api
NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)


async def _report(conn, collected_at: datetime = NOW, created_at: datetime = NOW) -> uuid.UUID:
    rid = uuid.uuid4()
    await conn.execute(text(
        "INSERT INTO lab_reports (id, patient_id, collected_at, entered_by, created_at) "
        "VALUES (:id, :p, :c, :u, :cr)"),
        {"id": rid, "p": uuid.uuid4(), "c": collected_at, "u": uuid.uuid4(), "cr": created_at})
    return rid


async def _result(conn, report_id: uuid.UUID, value: float = 1.0, flag: str = "normal",
                  supersedes: uuid.UUID | None = None) -> uuid.UUID:
    rid = uuid.uuid4()
    await conn.execute(text(
        "INSERT INTO lab_results (id, report_id, patient_id, collected_at, test_code, value, unit, "
        "value_original, unit_original, flag, supersedes_id, created_at) "
        "SELECT :id, :r, patient_id, collected_at, 'CREAT', :v, 'mg/dL', :v, 'mg/dL', :f, :s, :cr "
        "FROM lab_reports WHERE id = :r"),
        {"id": rid, "r": report_id, "v": value, "f": flag, "s": supersedes, "cr": NOW})
    return rid


async def test_results_cannot_be_updated(db_engine) -> None:
    async with db_engine.connect() as conn:
        rid = await _result(conn, await _report(conn))
        with pytest.raises(DBAPIError) as e:
            await conn.execute(text("UPDATE lab_results SET value = 9 WHERE id = :i"), {"i": rid})
        assert getattr(e.value.orig.__cause__, "hint", None) == "LAB_APPEND_ONLY"


async def test_results_cannot_be_deleted(db_engine) -> None:
    async with db_engine.connect() as conn:
        rid = await _result(conn, await _report(conn))
        await conn.commit()
    async with db_engine.connect() as conn:
        with pytest.raises(DBAPIError):
            await conn.execute(text("DELETE FROM lab_results WHERE id = :i"), {"i": rid})


async def test_reports_cannot_be_updated_or_deleted(db_engine) -> None:
    async with db_engine.connect() as conn:
        rid = await _report(conn)
        await conn.commit()
    for sql in ("UPDATE lab_reports SET notes = 'x' WHERE id = :i", "DELETE FROM lab_reports WHERE id = :i"):
        async with db_engine.connect() as conn:
            with pytest.raises(DBAPIError):
                await conn.execute(text(sql), {"i": rid})


async def test_negative_value_rejected(db_engine) -> None:
    async with db_engine.connect() as conn:
        with pytest.raises(IntegrityError):
            await _result(conn, await _report(conn), value=-1)


async def test_unknown_flag_value_rejected_but_unknown_allowed(db_engine) -> None:
    async with db_engine.connect() as conn:
        rep = await _report(conn)
        await _result(conn, rep, flag="unknown")           # an unmatched range is a legal flag
    async with db_engine.connect() as conn:
        rep = await _report(conn)
        with pytest.raises(IntegrityError):
            await _result(conn, rep, flag="severe")


async def test_future_collection_date_rejected(db_engine) -> None:
    async with db_engine.connect() as conn:
        with pytest.raises(IntegrityError):
            await _report(conn, collected_at=NOW + timedelta(days=1))


async def test_a_result_can_be_corrected_only_once(db_engine) -> None:
    async with db_engine.connect() as conn:
        rep = await _report(conn)
        first = await _result(conn, rep)
        await _result(conn, rep, value=2, supersedes=first)
        with pytest.raises(IntegrityError):
            await _result(conn, rep, value=3, supersedes=first)


async def test_unknown_test_code_rejected(db_engine) -> None:
    async with db_engine.connect() as conn:
        rep = await _report(conn)
        with pytest.raises(IntegrityError):
            await conn.execute(text(
                "INSERT INTO lab_results (report_id, patient_id, collected_at, test_code, value, unit, "
                "value_original, unit_original, flag, created_at) "
                "SELECT :r, patient_id, collected_at, 'NOPE', 1, 'x', 1, 'x', 'normal', :cr "
                "FROM lab_reports WHERE id = :r"), {"r": rep, "cr": NOW})


async def test_trigger_rejection_maps_to_nothing_leaky(db_engine) -> None:
    async with db_engine.connect() as conn:
        rid = await _result(conn, await _report(conn))
        with pytest.raises(DBAPIError) as e:
            await conn.execute(text("UPDATE lab_results SET value = 9 WHERE id = :i"), {"i": rid})
        assert map_db_error(e.value) is None        # surfaces as a 500 + logged hint: it is a service bug


async def test_role_cannot_connect_to_other_services_databases(migrated_db: str) -> None:
    from sqlalchemy.ext.asyncio import create_async_engine
    other = migrated_db.rsplit("/", 1)[0] + "/nephro_patient_db"
    engine = create_async_engine(other)
    with pytest.raises(Exception, match="permission denied|CONNECT"):
        async with engine.connect():
            pass
    await engine.dispose()
