"""argon2id in a worker thread under a semaphore (LLD §20.4). Plaintext is never stored or logged."""
from __future__ import annotations

import asyncio
import secrets
import time
from contextlib import asynccontextmanager

import anyio
from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import Settings
from app.core.errors import ServiceBusy
from app.core.metrics import ARGON2_INFLIGHT, ARGON2_REJECTED, ARGON2_SECONDS


class PasswordHasherService:
    def __init__(self, s: Settings) -> None:
        self._ph = PasswordHasher(time_cost=s.argon2_time_cost, memory_cost=s.argon2_memory_kib,
                                  parallelism=s.argon2_parallelism, type=Type.ID)
        self._sem = asyncio.Semaphore(s.argon2_max_concurrency)  # bulkhead on memory and CPU
        self._queue_timeout = s.argon2_queue_timeout_s
        self._dummy = self._ph.hash(secrets.token_urlsafe(24))   # same cost params as real hashes

    @asynccontextmanager
    async def _slot(self):
        """A hash slot, waiting at most ``argon2_queue_timeout_s``. A bounded queue turns overload into a
        fast 503 instead of unbounded latency and memory growth."""
        try:
            await asyncio.wait_for(self._sem.acquire(), timeout=self._queue_timeout)
        except TimeoutError as exc:
            ARGON2_REJECTED.inc()
            raise ServiceBusy() from exc
        try:
            yield
        finally:
            self._sem.release()

    async def hash(self, password: str) -> str:
        async with self._slot():
            return await self._timed("hash", self._ph.hash, password)

    async def verify(self, encoded: str, password: str) -> bool:
        async with self._slot():
            try:
                return await self._timed("verify", self._ph.verify, encoded, password)
            except (VerifyMismatchError, VerificationError, InvalidHashError):
                return False

    async def verify_dummy(self, password: str) -> None:
        """Burn the same CPU as a real verify so unknown emails cannot be timed."""
        await self.verify(self._dummy, password)

    def needs_rehash(self, encoded: str) -> bool:
        return self._ph.check_needs_rehash(encoded)

    @staticmethod
    async def _timed(op: str, fn, *args):
        ARGON2_INFLIGHT.inc()
        start = time.perf_counter()
        try:
            return await anyio.to_thread.run_sync(fn, *args)
        finally:
            ARGON2_INFLIGHT.dec()
            ARGON2_SECONDS.labels(op).observe(time.perf_counter() - start)
