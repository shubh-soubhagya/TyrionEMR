"""Periodic purge of long-expired refresh tokens (LLD §20.8)."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.domain.clock import Clock
from app.repositories.auth_event_repository import AuthEventRepository
from app.repositories.refresh_token_repository import RefreshTokenRepository

log = logging.getLogger("auth.cleanup")
CLEANUP_LOCK_ID = 727_101


async def run_cleanup_once(sm: async_sessionmaker[AsyncSession], s: Settings, clock: Clock) -> int | None:
    """Returns rows deleted, or None if another replica holds the lock."""
    async with sm() as session, session.begin():
        got = (await session.execute(text("SELECT pg_try_advisory_xact_lock(:k)"),
                                     {"k": CLEANUP_LOCK_ID})).scalar()
        if not got:        # only one replica does the work; the xact lock frees itself on commit
            return None
        n = await RefreshTokenRepository().delete_expired(
            session, before=clock() - timedelta(days=s.refresh_retention_days))
        events = await AuthEventRepository().delete_older_than(
            session, before=clock() - timedelta(days=s.auth_events_retention_days))
    log.info("auth.cleanup.done", extra={"deleted": n, "events_deleted": events})
    return n


async def run_cleanup_forever(sm: async_sessionmaker[AsyncSession], s: Settings, clock: Clock) -> None:
    while True:
        try:
            await run_cleanup_once(sm, s, clock)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("auth.cleanup.failed")
        await asyncio.sleep(s.cleanup_interval_s)
