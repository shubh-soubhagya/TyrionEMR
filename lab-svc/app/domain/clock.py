"""Injectable clock. Every timestamp the service writes or compares comes from here, never SQL now().

Timestamps are UTC; date-only rules ("today") use CLINIC_TZ so a follow-up date does not flip at
05:30 IST because the server runs in UTC (P-09).
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

Clock = Callable[[], datetime]


def utcnow() -> datetime:
    return datetime.now(UTC)


def today_in(clock: Clock, tz_name: str) -> date:
    return clock().astimezone(ZoneInfo(tz_name)).date()


class FakeClock:
    """Test clock: starts at a fixed instant and only moves when told to."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 11, 11, 12, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self._now

    def advance(self, **kwargs: float) -> None:
        self._now += timedelta(**kwargs)
