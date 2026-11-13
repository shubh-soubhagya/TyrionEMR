"""Rebuild and verify patient_lab_status (LLD B11.3).

The read model is derived data. ``rebuild`` recomputes it with the SAME function the write path uses
(``refresh_status``); ``check`` recomputes in memory and reports any patient whose stored row differs, writing
nothing. CI runs ``check`` after the API suite: that proves the incremental path and a full rebuild always agree.
"""
from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.domain.constants import RULES_VERSION
from app.domain.status import build_status
from app.models import LabReport, PatientLabStatus
from app.repositories.labs import LabRepository
from app.services.reports import refresh_status

# columns compared by check(); version and updated_at change on every recompute and are ignored
COMPARED = ("latest", "egfr_category", "uacr_category", "egfr_stats", "creat_stats", "egfr_spark", "has_critical",
            "rapid_decline", "result_count", "last_result_at", "first_result_at", "egfr_lt60_run", "rules_version")


@dataclass(frozen=True, slots=True)
class RebuildResult:
    rebuilt: int
    skipped: int = 0


async def patient_ids(sm: async_sessionmaker[AsyncSession], after: uuid.UUID | None = None,
                      page: int = 500) -> AsyncIterator[uuid.UUID]:
    """Every patient with at least one report, in id order, streamed in pages (never all in memory)."""
    cursor = after
    while True:
        async with sm() as s, s.begin():
            q = select(LabReport.patient_id).distinct().order_by(LabReport.patient_id).limit(page)
            if cursor:
                q = q.where(LabReport.patient_id > cursor)
            ids = list((await s.scalars(q)).all())
        if not ids:
            return
        for pid in ids:
            yield pid
        cursor = ids[-1]


async def _stored_rules_version(sm: async_sessionmaker[AsyncSession], pid: uuid.UUID) -> str | None:
    async with sm() as s, s.begin():
        row = await s.get(PatientLabStatus, pid)
        return None if row is None else row.rules_version


async def rebuild(sm: async_sessionmaker[AsyncSession], settings: Settings, *, patient: uuid.UUID | None = None,
                  stale_only: bool = False) -> RebuildResult:
    done = skipped = 0
    source = _one(patient) if patient else patient_ids(sm)
    async for pid in source:
        if stale_only and await _stored_rules_version(sm, pid) == RULES_VERSION:
            skipped += 1
            continue
        async with sm() as s, s.begin():
            repo = LabRepository(s)
            await repo.lock_patient(pid)                     # the same lock as the write path
            await refresh_status(repo, pid, settings.trend_config(), settings.spark_points)
        done += 1
    return RebuildResult(done, skipped)


async def _one(pid: uuid.UUID) -> AsyncIterator[uuid.UUID]:
    yield pid


def _norm(v: Any) -> Any:
    """JSON round trip so a computed dict and a jsonb column compare equal (44 == 44.0)."""
    return json.loads(json.dumps(v, default=lambda o: o.isoformat() if hasattr(o, "isoformat") else str(o)))


async def check(sm: async_sessionmaker[AsyncSession], settings: Settings,
                *, patient: uuid.UUID | None = None) -> list[tuple[uuid.UUID, list[str]]]:
    """Patients whose stored row differs from a fresh computation, with the differing columns. Writes nothing."""
    bad: list[tuple[uuid.UUID, list[str]]] = []
    seen: set[uuid.UUID] = set()
    async for pid in (_one(patient) if patient else patient_ids(sm)):
        seen.add(pid)
        async with sm() as s, s.begin():
            repo = LabRepository(s)
            expected = build_status(await repo.effective_points(pid), settings.trend_config(), settings.spark_points)
            row = await repo.status(pid)
        if row is None:
            bad.append((pid, ["<missing row>"]))
            continue
        diff = [c for c in COMPARED if _norm(getattr(row, c)) != _norm(expected[c])]
        if diff:
            bad.append((pid, diff))
    if patient is None:                                       # a status row for a patient with no reports at all
        async with sm() as s, s.begin():
            for pid in (await s.scalars(select(PatientLabStatus.patient_id))).all():
                if pid not in seen:
                    bad.append((pid, ["<orphan row>"]))
    return bad
