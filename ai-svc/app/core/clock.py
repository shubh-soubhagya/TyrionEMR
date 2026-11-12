"""Injectable clock. ``today()`` is the clinic date (CLINIC_TZ) used by every date rule (B2, B4)."""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

Clock = Callable[[], datetime]          # returns an aware UTC datetime


def utcnow() -> datetime:
    return datetime.now(UTC)


def clinic_today(clock: Clock, tz: str) -> date:
    return clock().astimezone(ZoneInfo(tz)).date()


class FakeClock:
    """Test clock: fixed until ``set``/``advance`` is called."""

    def __init__(self, now: datetime) -> None:
        self._now = now

    def __call__(self) -> datetime:
        return self._now

    def set(self, now: datetime) -> None:
        self._now = now
