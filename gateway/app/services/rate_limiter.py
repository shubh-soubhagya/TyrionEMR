"""In-memory rate limiter (LLD §21.2, ADR-G8)."""
from __future__ import annotations

from collections import OrderedDict
from typing import Protocol

from app.core.metrics import RATE_LIMITED
from app.domain.clock import Clock
from app.domain.token_bucket import Bucket, Decision, take
from app.routing.policies import Policy


class RateLimiter(Protocol):
    def check(self, policy: Policy, key: str) -> Decision: ...


class InMemoryRateLimiter:
    """Exact for one process (UVICORN_WORKERS=1). No awaits inside check(), so it is atomic on the
    event loop without a lock. LRU-capped so a flood of distinct keys cannot exhaust memory."""

    def __init__(self, clock: Clock, max_keys: int) -> None:
        self._clock, self._max = clock, max_keys
        self._buckets: OrderedDict[str, Bucket] = OrderedDict()

    def __len__(self) -> int:
        return len(self._buckets)

    def check(self, policy: Policy, key: str) -> Decision:
        k = f"{policy.name}:{key}"
        bucket, decision = take(self._buckets.pop(k, None), self._clock.monotonic(),
                                policy.burst, policy.per_min / 60.0)
        self._buckets[k] = bucket                     # (re)insert at the end: most recently used
        if len(self._buckets) > self._max:
            self._buckets.popitem(last=False)
        if not decision.allowed:
            RATE_LIMITED.labels(policy=policy.name).inc()
        return decision


class DisabledRateLimiter:
    def check(self, policy: Policy, key: str) -> Decision:
        return Decision(True, policy.burst, 0)
