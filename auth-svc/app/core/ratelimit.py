"""In-memory per-key token bucket (defense in depth until the gateway exists).

Limits are PER PROCESS: with 2 Uvicorn workers the effective limit is 2x. The gateway's limiter is the
real one; this only blunts abuse if auth-svc is ever reached directly. The key map is bounded (LRU
eviction) so a flood of distinct source addresses cannot grow memory without limit.
"""
from __future__ import annotations

import math
from collections import OrderedDict

from fastapi import Request

from app.core.config import Settings
from app.core.errors import RateLimited
from app.core.metrics import RATE_LIMITED
from app.domain.clock import Clock


class TokenBucketLimiter:
    def __init__(self, per_min: float, burst: int, clock: Clock, max_keys: int = 10_000) -> None:
        self._rate = per_min / 60.0          # tokens per second
        self._burst = float(burst)
        self._clock = clock
        self._max_keys = max_keys
        self._buckets: OrderedDict[str, tuple[float, float]] = OrderedDict()   # key -> (tokens, last_ts)

    def __len__(self) -> int:
        return len(self._buckets)

    def check(self, key: str) -> int:
        """0 if the request is allowed (and a token is spent), else whole seconds until one is available."""
        now = self._clock().timestamp()
        tokens, last = self._buckets.get(key, (self._burst, now))
        tokens = min(self._burst, tokens + max(0.0, now - last) * self._rate)
        if tokens >= 1.0:
            result, tokens = 0, tokens - 1.0
        else:
            result = max(1, math.ceil((1.0 - tokens) / self._rate)) if self._rate > 0 else 3600
        self._buckets[key] = (tokens, now)
        self._buckets.move_to_end(key)
        while len(self._buckets) > self._max_keys:
            self._buckets.popitem(last=False)     # evict the least recently used
        return result


def client_key(request: Request) -> str:
    # Behind the gateway uvicorn (--proxy-headers) puts the forwarded client address here.
    return request.client.host if request.client else "unknown"


async def rate_limit(request: Request) -> None:
    """FastAPI dependency for /auth/login and /auth/signup."""
    settings: Settings = request.app.state.settings
    if not settings.rate_limit_enabled:
        return
    wait = request.app.state.rate_limiter.check(client_key(request))
    if wait:
        RATE_LIMITED.labels(request.url.path).inc()
        raise RateLimited(retry_after=wait)
