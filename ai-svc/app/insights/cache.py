"""TTL snapshot cache with single-flight (LLD B11.2).

* A fresh snapshot is served without any upstream call.
* On a miss (or ``force``), the first caller starts the computation; concurrent callers await the same task.
* The computation runs as its own task, so the first caller disconnecting does not fail everyone else.
* A failed computation leaves nothing behind: a stale snapshot is never served after an error, because a dashboard
  that silently shows old critical results is worse than an error panel.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable


class SnapshotCache[T]:
    def __init__(self, ttl_s: float, mono: Callable[[], float] = time.monotonic) -> None:
        self._ttl = ttl_s
        self._mono = mono
        self._value: T | None = None
        self._stored_at = 0.0
        self._inflight: asyncio.Task[T] | None = None

    def peek(self) -> T | None:
        return self._value if self._fresh() else None

    def _fresh(self) -> bool:
        return self._value is not None and self._mono() - self._stored_at < self._ttl

    async def get(self, compute: Callable[[], Awaitable[T]], *, force: bool = False) -> tuple[T, str]:
        """Returns (snapshot, outcome) where outcome is 'hit', 'miss' or 'joined' (metrics label)."""
        if not force and self._fresh():
            assert self._value is not None
            return self._value, "hit"
        joined = self._inflight is not None
        if self._inflight is None:
            self._inflight = asyncio.create_task(self._run(compute))
        return await asyncio.shield(self._inflight), "joined" if joined else "miss"

    async def _run(self, compute: Callable[[], Awaitable[T]]) -> T:
        try:
            value = await compute()
        except BaseException:
            self._value = None
            raise
        else:
            self._value, self._stored_at = value, self._mono()
            return value
        finally:
            self._inflight = None

    def clear(self) -> None:
        self._value = None
