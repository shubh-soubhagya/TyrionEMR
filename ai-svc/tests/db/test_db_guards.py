"""Database guards and repositories against the real test database (LLD B3, B15, B17.3)."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.dberrors import _pg_exc, sqlstate_of
from app.repositories import summaries as repo
from app.repositories import tool_calls

pytestmark = pytest.mark.api

PATIENT, USER = uuid.uuid4(), uuid.uuid4()
HASH = "a" * 64
COMMON = dict(provider="groq", model="openai/gpt-oss-20b", prompt_version="v1", schema_version="out-1",
              rules_version="ai-rules-1", tools_enabled=True)


@pytest.fixture
def sm(db_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(db_engine, expire_on_commit=False)


async def new_running(sm, patient=PATIENT, user=USER, **kw):
    async with sm() as s, s.begin():
        return await repo.insert_running(s, patient_id=patient, requested_by=user, request_id="r", force=False,
                                         **(COMMON | kw))


def original_fields(**over):
    return dict(context_hash=HASH, context_snapshot={"packet": {}}, facts={"f": 1}, gaps={"g": 1}, output={"o": 1},
                sources={}, validation={"schema_valid": True}, attempts=1) | over


async def finish(sm, sid, status, **fields):
    async with sm() as s, s.begin():
        return await repo.finish(s, sid, status, **fields)


# ---- single-flight ----------------------------------------------------------------------------
async def test_second_running_job_for_same_pair_is_refused_not_an_error(sm):
    first = await new_running(sm)
    assert first is not None and first["status"] == "running"
    assert len(first["progress"]) == 7 and first["progress"][0]["state"] == "running"
    assert await new_running(sm) is None                                   # ON CONFLICT DO NOTHING
    async with sm() as s:
        winner = await repo.find_running(s, PATIENT, USER)
    assert winner["id"] == first["id"]


async def test_other_clinician_or_patient_may_run_in_parallel(sm):
    assert await new_running(sm) is not None
    assert await new_running(sm, user=uuid.uuid4()) is not None
    assert await new_running(sm, patient=uuid.uuid4()) is not None


async def test_a_new_job_is_allowed_once_the_previous_one_finished(sm):
    first = await new_running(sm)
    assert await finish(sm, first["id"], "failed", error_code="UPSTREAM_UNAVAILABLE")
    assert await new_running(sm) is not None


# ---- progress and heartbeat -------------------------------------------------------------------
async def test_progress_write_updates_heartbeat_and_is_validated(sm):
    row = await new_running(sm)
    steps = [dict(s) for s in row["progress"]]
    steps[0].update(state="done", ms=40, note="Ready")
    steps[1]["state"] = "running"
    async with sm() as s, s.begin():
        assert await repo.write_progress(s, row["id"], steps)
        assert await repo.heartbeat(s, row["id"])
    async with sm() as s:
        assert (await repo.get(s, row["id"]))["progress"][0]["state"] == "done"
    with pytest.raises(ValueError):
        async with sm() as s, s.begin():
            await repo.write_progress(s, row["id"], steps[:3])            # must be all seven steps in order


async def test_writes_to_a_finished_job_update_nothing(sm):
    """The reaper and a finishing job can both try; only the first to commit wins (B15)."""
    row = await new_running(sm)
    assert await finish(sm, row["id"], "failed", error_code="JOB_TIMEOUT")
    async with sm() as s, s.begin():
        assert not await repo.heartbeat(s, row["id"])
        assert not await repo.write_progress(s, row["id"], row["progress"])
    assert not await finish(sm, row["id"], "failed", error_code="INTERNAL_ERROR")


# ---- terminal shapes (B3.2 constraint table) --------------------------------------------------
async def test_completed_original_needs_every_part(sm):
    row = await new_running(sm)
    with pytest.raises(IntegrityError) as e:
        await finish(sm, row["id"], "completed", **original_fields(sources=None))
    assert "completed_original_shape" in str(e.value)


async def test_completed_original_with_all_parts_is_accepted(sm):
    row = await new_running(sm)
    assert await finish(sm, row["id"], "completed", **original_fields())


async def test_degraded_needs_facts_gaps_error_and_no_output(sm):
    row = await new_running(sm)
    with pytest.raises(IntegrityError) as e:
        await finish(sm, row["id"], "degraded", facts={"f": 1}, gaps={"g": 1}, output={"o": 1}, error_code="LLM_TIMEOUT")
    assert "degraded_shape" in str(e.value)
    assert await finish(sm, row["id"], "degraded", facts={"f": 1}, gaps={"g": 1}, error_code="LLM_TIMEOUT")


async def test_failed_needs_a_code_and_no_output(sm):
    row = await new_running(sm)
    with pytest.raises(IntegrityError) as e:
        await finish(sm, row["id"], "failed")
    assert "failed_shape" in str(e.value)


async def test_error_codes_are_a_closed_set(sm):
    row = await new_running(sm)
    with pytest.raises(IntegrityError) as e:
        await finish(sm, row["id"], "failed", error_code="SOMETHING_ELSE")
    assert "error_code_values" in str(e.value)


async def test_cache_hit_carries_no_output_and_no_attempts(sm):
    orig = await new_running(sm)
    await finish(sm, orig["id"], "completed", **original_fields())
    hit = await new_running(sm)
    with pytest.raises(IntegrityError) as e:
        await finish(sm, hit["id"], "completed", cached_from=orig["id"], output={"o": 1}, attempts=0)
    assert "cache_hit_shape" in str(e.value)
    assert await finish(sm, hit["id"], "completed", cached_from=orig["id"], attempts=0)


async def test_bad_hash_and_unknown_provider_are_rejected(sm):
    row = await new_running(sm)
    with pytest.raises(IntegrityError) as e:
        await finish(sm, row["id"], "completed", **original_fields(context_hash="XYZ"))
    assert "hash_format" in str(e.value)
    with pytest.raises(IntegrityError):
        await new_running(sm, patient=uuid.uuid4(), provider="openai")


# ---- immutability triggers --------------------------------------------------------------------
async def test_update_of_a_final_row_is_rejected_by_the_trigger(db_engine, sm):
    row = await new_running(sm)
    await finish(sm, row["id"], "failed", error_code="JOB_TIMEOUT")
    with pytest.raises(DBAPIError) as e:
        async with db_engine.begin() as c:
            await c.execute(text("UPDATE ai_summaries SET error_code = 'INTERNAL_ERROR' WHERE id = :i"), {"i": row["id"]})
    assert sqlstate_of(e.value) == "P0001" and _pg_exc(e.value).hint == "SUMMARY_FINAL"


async def test_rows_are_never_deleted(db_engine, sm):
    row = await new_running(sm)
    with pytest.raises(DBAPIError) as e:
        async with db_engine.begin() as c:
            await c.execute(text("DELETE FROM ai_summaries WHERE id = :i"), {"i": row["id"]})
    assert sqlstate_of(e.value) == "P0001" and _pg_exc(e.value).hint == "NO_DELETE"


async def test_identity_columns_cannot_change_while_running(db_engine, sm):
    row = await new_running(sm)
    with pytest.raises(DBAPIError) as e:
        async with db_engine.begin() as c:
            await c.execute(text("UPDATE ai_summaries SET patient_id = :p WHERE id = :i"),
                            {"p": uuid.uuid4(), "i": row["id"]})
    assert _pg_exc(e.value).hint == "IMMUTABLE_COLUMN"


async def test_tool_calls_are_append_only_and_only_for_running_jobs(db_engine, sm):
    row = await new_running(sm)
    async with sm() as s, s.begin():
        await tool_calls.append(s, summary_id=row["id"], seq=1, iteration=1, tool_name="get_lab_trend",
                                arguments={"test_code": "EGFR"}, status="ok", latency_ms=12, result_rows=8)
        await tool_calls.append(s, summary_id=row["id"], seq=2, iteration=1, tool_name="Not A Tool!",
                                arguments={}, status="rejected", latency_ms=1)
    async with sm() as s:
        rows = await tool_calls.list_for(s, row["id"])
    assert [r["tool_name"] for r in rows] == ["get_lab_trend", "unknown"] and rows[1]["arguments"]["_name"] == "Not A Tool!"
    with pytest.raises(DBAPIError) as e:
        async with db_engine.begin() as c:
            await c.execute(text("UPDATE llm_tool_calls SET status = 'error'"))
    assert _pg_exc(e.value).hint == "APPEND_ONLY"
    await finish(sm, row["id"], "failed", error_code="JOB_ABORTED")
    with pytest.raises(DBAPIError) as e:
        async with sm() as s, s.begin():
            await tool_calls.append(s, summary_id=row["id"], seq=3, iteration=2, tool_name="x", arguments={},
                                    status="ok", latency_ms=1)
    assert _pg_exc(e.value).hint == "SUMMARY_FINAL"


async def test_duplicate_tool_call_sequence_is_rejected(sm):
    row = await new_running(sm)
    kw = dict(summary_id=row["id"], seq=1, iteration=1, tool_name="t", arguments={}, status="ok", latency_ms=1)
    async with sm() as s, s.begin():
        await tool_calls.append(s, **kw)
    with pytest.raises(IntegrityError):
        async with sm() as s, s.begin():
            await tool_calls.append(s, **kw)


async def test_truncate_still_works_for_test_fixtures(db_engine, sm):
    await new_running(sm)
    async with db_engine.begin() as c:
        await c.execute(text("TRUNCATE llm_tool_calls, ai_summaries"))
        assert (await c.execute(text("SELECT count(*) FROM ai_summaries"))).scalar() == 0


# ---- queries ----------------------------------------------------------------------------------
async def test_cache_source_is_completed_originals_only(sm):
    deg = await new_running(sm)
    await finish(sm, deg["id"], "degraded", context_hash=HASH, facts={"f": 1}, gaps={"g": 1}, error_code="LLM_TIMEOUT")
    async with sm() as s:
        assert await repo.find_cache_source(s, PATIENT, HASH) is None      # degraded is never a cache source
    ok = await new_running(sm)
    await finish(sm, ok["id"], "completed", **original_fields())
    hit = await new_running(sm)
    await finish(sm, hit["id"], "completed", cached_from=ok["id"], attempts=0, context_hash=HASH)
    async with sm() as s:
        src = await repo.find_cache_source(s, PATIENT, HASH)
        assert src["id"] == ok["id"]                                        # not the cache hit
        assert await repo.find_cache_source(s, uuid.uuid4(), HASH) is None  # patient_id is in the lookup


async def test_history_lists_completed_and_degraded_originals_newest_first(sm):
    ids = []
    for status in ("completed", "degraded", "failed", "completed"):
        row = await new_running(sm)
        if status == "completed":
            await finish(sm, row["id"], status, **original_fields(context_hash=uuid.uuid4().hex * 2))
        elif status == "degraded":
            await finish(sm, row["id"], status, facts={}, gaps={}, error_code="LLM_UNAVAILABLE")
        else:
            await finish(sm, row["id"], status, error_code="UPSTREAM_UNAVAILABLE")
        ids.append(row["id"])
    async with sm() as s:
        rows, total = await repo.history(s, PATIENT, 1, 10)
        assert total == 3 and [r["id"] for r in rows] == [ids[3], ids[1], ids[0]]
        page2, _ = await repo.history(s, PATIENT, 2, 2)
        assert [r["id"] for r in page2] == [ids[0]]


async def test_quota_counts_llm_calling_and_running_jobs_only(sm):
    from datetime import UTC, datetime, timedelta
    start, end = datetime.now(UTC) - timedelta(hours=1), datetime.now(UTC) + timedelta(hours=1)
    ran = await new_running(sm, patient=uuid.uuid4())
    await finish(sm, ran["id"], "completed", **original_fields())            # attempts=1: counts
    early = await new_running(sm, patient=uuid.uuid4())
    await finish(sm, early["id"], "failed", error_code="UPSTREAM_UNAVAILABLE")  # never reached the model: free
    hit = await new_running(sm, patient=uuid.uuid4())
    await finish(sm, hit["id"], "completed", cached_from=ran["id"], attempts=0)  # cache hit: free
    await new_running(sm, patient=uuid.uuid4())                              # still running: counts
    async with sm() as s:
        assert await repo.count_quota(s, USER, start, end) == 2
        assert await repo.count_quota(s, USER, start - timedelta(days=2), start) == 0


async def test_reaper_fails_only_stale_running_rows(db_engine, sm):
    stale = await new_running(sm, patient=uuid.uuid4())
    fresh = await new_running(sm, patient=uuid.uuid4())
    async with db_engine.begin() as c:       # age one heartbeat; direct UPDATE is allowed while running
        await c.execute(text("UPDATE ai_summaries SET heartbeat_at = now() - interval '300 seconds' WHERE id = :i"),
                        {"i": stale["id"]})
    async with sm() as s, s.begin():
        assert await repo.reap_stale(s, 120) == [stale["id"]]
    async with sm() as s:
        assert (await repo.get(s, stale["id"]))["error_code"] == "JOB_TIMEOUT"
        assert (await repo.get(s, fresh["id"]))["status"] == "running"
    async with sm() as s, s.begin():
        assert await repo.reap_stale(s, 120) == []                            # idempotent


async def test_quota_lock_serialises_concurrent_requests(db_engine, sm):
    """The advisory lock is per user: a second transaction for the same user waits until the first commits."""
    import asyncio
    order: list[str] = []

    async def worker(name: str, hold: float):
        async with sm() as s, s.begin():
            await repo.lock_user_quota(s, USER)
            order.append(f"{name}-in")
            await asyncio.sleep(hold)
            order.append(f"{name}-out")

    await asyncio.gather(worker("a", 0.3), _after(0.05, worker("b", 0)))
    assert order == ["a-in", "a-out", "b-in", "b-out"]


async def _after(delay: float, coro):
    import asyncio
    await asyncio.sleep(delay)
    return await coro
