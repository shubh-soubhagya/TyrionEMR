"""Stale-job reaper (LLD B10.7). One UPDATE, safe on any number of replicas: only one can match a given row."""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.metrics import AI_REAPED
from app.repositories import summaries as repo

log = logging.getLogger("ai.reaper")


async def reap_once(sessionmaker: async_sessionmaker[AsyncSession], ttl_s: float) -> list:
    async with sessionmaker() as s, s.begin():
        ids = await repo.reap_stale(s, ttl_s)
    if ids:
        AI_REAPED.inc(len(ids))
        log.warning("reaper.failed_jobs", extra={"count": len(ids), "ids": [str(i) for i in ids]})
    return ids


async def run_forever(sessionmaker: async_sessionmaker[AsyncSession], ttl_s: float, interval_s: float) -> None:
    while True:
        try:
            await reap_once(sessionmaker, ttl_s)
        except Exception as exc:                 # the database may be down; the next tick tries again
            log.warning("reaper.error", extra={"error_type": type(exc).__name__})
        await asyncio.sleep(interval_s)
