"""ai_summaries access (LLD B3, B10, B15). Repositories receive a session and never commit: the service owns the
transaction boundary. Every write to a live job is guarded by ``status = 'running'`` so a reaper and a finishing
job can never both win (B15)."""
from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Integer, cast, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.tables import ai_summaries as t
from app.schemas.jsonb import initial_progress, validate_progress

Row = Mapping[str, Any]
TERMINAL = ("completed", "degraded", "failed")

# Columns a final write may set (everything else is identity or lifecycle).
_FINAL_COLUMNS = frozenset({
    "cached_from", "context_hash", "context_snapshot", "facts", "gaps", "output", "sources", "validation",
    "progress", "error_code", "attempts", "tool_call_count", "tokens_in", "tokens_out", "latency_ms",
})


async def lock_user_quota(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Per-user advisory lock held until the transaction ends: serialises 'count quota, then insert' (B10.3)."""
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"ai-quota:{user_id}"})


async def insert_running(session: AsyncSession, *, patient_id: uuid.UUID, requested_by: uuid.UUID,
                         request_id: str | None, force: bool, provider: str, model: str, prompt_version: str,
                         schema_version: str, rules_version: str, tools_enabled: bool) -> Row | None:
    """Inserts a ``running`` row. Returns None when the partial unique index says a job is already running for this
    (patient, clinician): single-flight, the caller then reads the winner (AI-ADR-2)."""
    stmt = (
        insert(t)
        .values(patient_id=patient_id, requested_by=requested_by, request_id=request_id, force=force,
                provider=provider, model=model, prompt_version=prompt_version, schema_version=schema_version,
                rules_version=rules_version, tools_enabled=tools_enabled, progress=initial_progress())
        .on_conflict_do_nothing(index_elements=[t.c.patient_id, t.c.requested_by],
                               index_where=text("status = 'running'"))
        .returning(t)
    )
    return (await session.execute(stmt)).mappings().first()


async def get(session: AsyncSession, summary_id: uuid.UUID) -> Row | None:
    return (await session.execute(select(t).where(t.c.id == summary_id))).mappings().first()


async def find_running(session: AsyncSession, patient_id: uuid.UUID, requested_by: uuid.UUID) -> Row | None:
    stmt = select(t).where(t.c.patient_id == patient_id, t.c.requested_by == requested_by, t.c.status == "running")
    return (await session.execute(stmt)).mappings().first()


async def write_progress(session: AsyncSession, summary_id: uuid.UUID, progress: list[dict]) -> bool:
    """One statement; also the heartbeat. False when the job is no longer running (reaped or finished)."""
    stmt = (update(t).where(t.c.id == summary_id, t.c.status == "running")
            .values(progress=validate_progress(progress), heartbeat_at=func.now()))
    return (await session.execute(stmt)).rowcount == 1


async def heartbeat(session: AsyncSession, summary_id: uuid.UUID) -> bool:
    stmt = update(t).where(t.c.id == summary_id, t.c.status == "running").values(heartbeat_at=func.now())
    return (await session.execute(stmt)).rowcount == 1


async def finish(session: AsyncSession, summary_id: uuid.UUID, status: str, **fields: Any) -> bool:
    """Final write: one statement guarded by ``status = 'running'``. The CHECK constraints validate the shape of
    each terminal state, so a wrong combination fails loudly instead of being stored."""
    if status not in TERMINAL:
        raise ValueError(f"not a terminal status: {status}")
    unknown = set(fields) - _FINAL_COLUMNS
    if unknown:
        raise ValueError(f"unknown final columns: {sorted(unknown)}")
    if "progress" in fields:
        fields["progress"] = validate_progress(fields["progress"])
    stmt = (update(t).where(t.c.id == summary_id, t.c.status == "running")
            .values(status=status, finished_at=func.now(), heartbeat_at=func.now(), **fields))
    return (await session.execute(stmt)).rowcount == 1


async def find_cache_source(session: AsyncSession, patient_id: uuid.UUID, context_hash: str) -> Row | None:
    """Completed originals only (AI-ADR-3): a degraded result is never replayed as the AI's answer."""
    stmt = (select(t).where(t.c.patient_id == patient_id, t.c.context_hash == context_hash,
                            t.c.status == "completed", t.c.cached_from.is_(None))
            .order_by(t.c.created_at.desc()).limit(1))
    return (await session.execute(stmt)).mappings().first()


async def history(session: AsyncSession, patient_id: uuid.UUID, page: int, size: int) -> tuple[Sequence[Row], int]:
    """Completed and degraded originals, newest first (served by ix_summaries_history)."""
    cond = (t.c.patient_id == patient_id, t.c.status.in_(("completed", "degraded")), t.c.cached_from.is_(None))
    total = (await session.execute(select(func.count()).select_from(t).where(*cond))).scalar_one()
    rows = (await session.execute(select(t).where(*cond).order_by(t.c.created_at.desc(), t.c.id)
                                  .limit(size).offset((page - 1) * size))).mappings().all()
    return rows, total


async def count_quota(session: AsyncSession, requested_by: uuid.UUID, start: datetime, end: datetime) -> int:
    """Jobs that called the LLM or are still running, excluding cache hits, in [start, end) (B10.3).
    A job that failed before reaching the model (attempts = 0, not running) does not consume quota."""
    stmt = (select(func.count()).select_from(t)
            .where(t.c.requested_by == requested_by, t.c.created_at >= start, t.c.created_at < end,
                   t.c.cached_from.is_(None), (t.c.status == "running") | (t.c.attempts > 0)))
    return (await session.execute(stmt)).scalar_one()


async def reap_stale(session: AsyncSession, ttl_s: float) -> list[uuid.UUID]:
    """Marks running jobs without a heartbeat for ``ttl_s`` as failed JOB_TIMEOUT. One statement, safe with any
    number of replicas: only one UPDATE can match a given row (B10.7)."""
    stmt = (update(t)
            .where(t.c.status == "running", t.c.heartbeat_at < func.now() - timedelta(seconds=ttl_s))
            .values(status="failed", error_code="JOB_TIMEOUT", finished_at=func.now(),
                    latency_ms=cast(func.extract("epoch", func.now() - t.c.started_at) * 1000, Integer))
            .returning(t.c.id))
    return [r[0] for r in (await session.execute(stmt)).all()]
