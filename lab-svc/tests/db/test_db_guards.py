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
        "INSERT INTO lab_reports (id, patient_id, collected_at, lab_name, entered_by, created_at) "
        "VALUES (:id, :p, :c, 'Test lab', :u, :cr)"),
        {"id": rid, "p": uuid.uuid4(), "c": collected_at, "u": uuid.uuid4(), "cr": created_at})
    return rid


async def _result(conn, report_id: uuid.UUID, value: float = 1.0, flag: str = "normal",
                  supersedes: uuid.UUID | None = None, test: str = "CREAT", reason: str | None = "auto",
                  with_range: bool | None = None, collected_at=None, rid: uuid.UUID | None = None) -> uuid.UUID:
    """Inserts one result row. ``reason="auto"`` supplies a reason exactly when ``supersedes`` is set."""
    rid = rid or uuid.uuid4()
    has_range = (flag != "unknown") if with_range is None else with_range
    why = ("test correction" if supersedes is not None else None) if reason == "auto" else reason
    await conn.execute(text(
        "INSERT INTO lab_results (id, report_id, patient_id, collected_at, test_code, value, unit, "
        "value_original, unit_original, range_id, flag, supersedes_id, correction_reason, entered_by, created_at) "
        "SELECT :id, :r, patient_id, COALESCE(:col, collected_at), :t, :v, 'u', :v, 'u', "
        "(CASE WHEN :hr THEN (SELECT id FROM lab_reference_ranges WHERE test_code = 'CREAT' AND sex = 'M') END), "
        ":f, :s, :why, entered_by, :cr FROM lab_reports WHERE id = :r"),
        {"id": rid, "r": report_id, "v": value, "f": flag, "s": supersedes, "cr": NOW, "t": test,
         "why": why, "hr": has_range, "col": collected_at})
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


async def test_flag_vocabulary_and_unknown_iff_no_range(db_engine) -> None:
    async with db_engine.connect() as conn:
        await _result(conn, await _report(conn), flag="unknown")               # no range, unknown: legal
    for kwargs in ({"flag": "severe"},                                          # not in the vocabulary
                   {"flag": "normal", "with_range": False},                      # never silently normal
                   {"flag": "unknown", "with_range": True}):
        async with db_engine.connect() as conn:
            with pytest.raises(IntegrityError):
                await _result(conn, await _report(conn), **kwargs)


async def test_collection_date_must_be_plausible(db_engine) -> None:
    async with db_engine.connect() as conn:
        with pytest.raises(IntegrityError):
            await _report(conn, collected_at=datetime(1850, 1, 1, tzinfo=UTC))


async def test_report_text_limits(db_engine) -> None:
    async with db_engine.connect() as conn:
        with pytest.raises(IntegrityError):
            await conn.execute(text(
                "INSERT INTO lab_reports (patient_id, collected_at, lab_name, entered_by, created_at) "
                "VALUES (gen_random_uuid(), :c, NULL, gen_random_uuid(), :c)"), {"c": NOW})
    async with db_engine.connect() as conn:
        with pytest.raises(IntegrityError):
            await conn.execute(text(
                "INSERT INTO lab_reports (patient_id, collected_at, lab_name, notes, entered_by, created_at) "
                "VALUES (gen_random_uuid(), :c, 'x', :n, gen_random_uuid(), :c)"), {"c": NOW, "n": "n" * 501})


async def test_a_result_can_be_corrected_only_once(db_engine) -> None:
    async with db_engine.connect() as conn:
        rep = await _report(conn)
        first = await _result(conn, rep)
        await _result(conn, rep, value=2, supersedes=first)
        with pytest.raises(IntegrityError):
            await _result(conn, rep, value=3, supersedes=first)


async def test_correction_needs_a_reason_and_only_corrections_have_one(db_engine) -> None:
    async with db_engine.connect() as conn:
        rep = await _report(conn)
        first = await _result(conn, rep)
        await conn.commit()
    async with db_engine.connect() as conn:
        with pytest.raises(IntegrityError):
            await _result(conn, rep, supersedes=first, reason=None)
    async with db_engine.connect() as conn:
        with pytest.raises(IntegrityError):
            await _result(conn, rep, test="K", reason="not a correction")
    async with db_engine.connect() as conn:
        with pytest.raises(IntegrityError):
            await _result(conn, rep, supersedes=first, reason="no")                # shorter than 3 characters


async def test_correction_must_match_report_and_test(db_engine) -> None:
    async with db_engine.connect() as conn:
        rep_a, rep_b = await _report(conn), await _report(conn)
        creat = await _result(conn, rep_a)
        await conn.commit()
    async with db_engine.connect() as conn:
        with pytest.raises(IntegrityError):                                          # other test
            await _result(conn, rep_a, test="K", supersedes=creat)
    async with db_engine.connect() as conn:
        with pytest.raises(IntegrityError):                                          # other report
            await _result(conn, rep_b, supersedes=creat)


async def test_self_supersede_rejected(db_engine) -> None:
    async with db_engine.connect() as conn:
        rep = await _report(conn)
        rid = uuid.uuid4()
        with pytest.raises(IntegrityError):
            await _result(conn, rep, supersedes=rid, rid=rid)


async def test_one_original_per_test_per_report(db_engine) -> None:
    async with db_engine.connect() as conn:
        rep = await _report(conn)
        await _result(conn, rep)
        with pytest.raises(IntegrityError):
            await _result(conn, rep)


async def test_result_cannot_drift_from_its_report(db_engine) -> None:
    async with db_engine.connect() as conn:
        rep = await _report(conn)
        with pytest.raises(IntegrityError):
            await _result(conn, rep, collected_at=NOW - timedelta(days=3))           # other collected_at than the report


async def test_current_view_excludes_superseded_rows(db_engine) -> None:
    async with db_engine.connect() as conn:
        rep = await _report(conn)
        first = await _result(conn, rep, value=1.0)
        second = await _result(conn, rep, value=2.0, supersedes=first)
        ids = {r[0] for r in await conn.execute(text("SELECT id FROM lab_results_current"))}
        assert ids == {second}


async def test_unknown_test_code_rejected(db_engine) -> None:
    async with db_engine.connect() as conn:
        rep = await _report(conn)
        with pytest.raises(IntegrityError):
            await _result(conn, rep, test="NOPE")


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
