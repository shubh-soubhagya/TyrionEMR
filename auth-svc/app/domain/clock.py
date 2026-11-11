"""Injectable clock. Every timestamp the service writes or compares comes from here, never SQL now()."""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

Clock = Callable[[], datetime]


def utcnow() -> datetime:
    return datetime.now(UTC)


class FakeClock:
    """Test clock: starts at a fixed instant and only moves when told to."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 11, 11, 12, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self._now

    def advance(self, **kwargs: float) -> None:
        self._now += timedelta(**kwargs)
