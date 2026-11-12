"""Injectable time (pure; no framework imports).

Two readings, as the design needs both: wall-clock seconds for token expiry and a monotonic reading for
rate limits, JWKS staleness and refetch spacing. ``FakeClock`` advances both together in tests.
"""
from __future__ import annotations

import time
from typing import Protocol


class Clock(Protocol):
    def wall(self) -> float: ...        # epoch seconds
    def monotonic(self) -> float: ...


class SystemClock:
    def wall(self) -> float:
        return time.time()

    def monotonic(self) -> float:
        return time.monotonic()


class FakeClock:
    def __init__(self, wall: float = 1_780_000_000.0, monotonic: float = 1000.0) -> None:
        self._wall, self._mono = wall, monotonic

    def wall(self) -> float:
        return self._wall

    def monotonic(self) -> float:
        return self._mono

    def advance(self, seconds: float) -> None:
        self._wall += seconds
        self._mono += seconds
