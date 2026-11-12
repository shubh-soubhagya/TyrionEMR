"""Pure token bucket (LLD §21.1)."""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Bucket:
    tokens: float
    updated: float          # monotonic seconds


@dataclass(frozen=True)
class Decision:
    allowed: bool
    remaining: int
    retry_after_s: int


def take(bucket: Bucket | None, now: float, capacity: int, refill_per_s: float) -> tuple[Bucket, Decision]:
    if bucket is None:
        bucket = Bucket(tokens=float(capacity), updated=now)
    tokens = min(float(capacity), bucket.tokens + max(0.0, now - bucket.updated) * refill_per_s)
    if tokens >= 1.0:
        tokens -= 1.0
        return Bucket(tokens, now), Decision(True, int(tokens), 0)
    wait = (1.0 - tokens) / refill_per_s
    return Bucket(tokens, now), Decision(False, 0, max(1, math.ceil(wait)))
