"""ProgressTracker (LLD B10.5): the seven visible steps, persisted after every change, doubling as the heartbeat.

Each write is its own short transaction. If a write updates zero rows the reaper already failed the job, so the
tracker raises ``JobGone`` and the job stops writing.
"""
from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.metrics import AI_STEP_DURATION
from app.repositories import summaries as repo
from app.schemas.jsonb import STEP_LABELS, initial_progress

SessionMaker = async_sessionmaker[AsyncSession]


class JobGone(Exception):
    """The row is no longer 'running' (reaped or already finished): stop writing."""


class ProgressTracker:
    def __init__(self, summary_id: uuid.UUID, sessionmaker: SessionMaker, mono: Callable[[], float] = time.monotonic,
                 steps: list[dict[str, Any]] | None = None) -> None:
        self.summary_id, self._sm, self._mono = summary_id, sessionmaker, mono
        self.steps = steps or initial_progress()
        self._started: dict[str, float] = {"open_chart": mono()}

    def _step(self, key: str) -> dict[str, Any]:
        return next(s for s in self.steps if s["key"] == key)

    async def flush(self) -> None:
        async with self._sm() as s, s.begin():
            if not await repo.write_progress(s, self.summary_id, self.steps):
                raise JobGone(str(self.summary_id))

    async def start(self, key: str, note: str | None = None) -> None:
        step = self._step(key)
        step.update(state="running", note=note)
        self._started[key] = self._mono()
        await self.flush()

    async def note(self, key: str, note: str) -> None:
        self._step(key)["note"] = note[:200]
        await self.flush()

    async def done(self, key: str, note: str | None = None) -> None:
        step = self._step(key)
        ms = round((self._mono() - self._started.get(key, self._mono())) * 1000)
        step.update(state="done", ms=ms, note=note[:200] if note else step.get("note"))
        AI_STEP_DURATION.labels(key).observe(ms / 1000)
        await self.flush()

    def mark_failed(self, key: str, note: str) -> None:
        """In memory only; the final write persists the whole progress array."""
        self._step(key).update(state="failed", note=note[:200])
        self.skip_rest(key)

    def skip(self, keys: list[str], note: str) -> None:
        for k in keys:
            step = self._step(k)
            if step["state"] in ("pending", "running"):
                step.update(state="skipped", note=note)

    def skip_rest(self, after: str, note: str = "Skipped") -> None:
        order = [k for k, _ in STEP_LABELS]
        self.skip(order[order.index(after) + 1:], note)
