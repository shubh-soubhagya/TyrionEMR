"""Trend statistics (LLD B4.5). Pure: no I/O. Thresholds come from ``TrendConfig`` (settings), not literals."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Final, Literal

Direction = Literal["improving", "stable", "worsening", "insufficient_data", "no_data", "not_assessed"]
SECONDS_PER_YEAR: Final = 365.25 * 86400


@dataclass(frozen=True, slots=True)
class Point:
    at: datetime
    value: Decimal


@dataclass(frozen=True, slots=True)
class TrendConfig:
    min_points: int = 3                       # below this, direction is insufficient_data (never extrapolate)
    egfr_stable_band: float = 2.0             # mL/min/1.73 m2 per year
    creat_stable_band: float = 0.1            # mg/dL per year
    egfr_rapid_decline: float = -5.0          # slope at or below this is rapid decline (KDIGO)


@dataclass(frozen=True, slots=True)
class TrendStats:
    n: int
    direction: Direction
    first: Decimal | None = None
    last: Decimal | None = None
    abs_change: Decimal | None = None
    pct_change: float | None = None
    slope_per_year: float | None = None
    rapid_decline: bool = False
    span_days: int | None = None
    first_at: datetime | None = None
    last_at: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        """JSON-safe form used by the read model and the trends endpoint."""
        if self.n == 0:
            return {"n": 0, "direction": "no_data"}
        assert self.first is not None and self.last is not None and self.abs_change is not None
        assert self.first_at is not None and self.last_at is not None
        return {"n": self.n, "first": float(self.first), "last": float(self.last),
                "abs_change": float(self.abs_change), "pct_change": self.pct_change,
                "slope_per_year": self.slope_per_year, "direction": self.direction,
                "rapid_decline": self.rapid_decline, "span_days": self.span_days,
                "first_at": self.first_at.isoformat(), "last_at": self.last_at.isoformat()}


def direction_for(test_code: str, slope: float, cfg: TrendConfig) -> Direction:
    if test_code == "EGFR":                          # a falling eGFR is worse; bands are inclusive
        if slope <= -cfg.egfr_stable_band:
            return "worsening"
        if slope >= cfg.egfr_stable_band:
            return "improving"
        return "stable"
    if test_code == "CREAT":                         # a rising creatinine is worse; bands are strict
        if slope > cfg.creat_stable_band:
            return "worsening"
        if slope < -cfg.creat_stable_band:
            return "improving"
        return "stable"
    return "not_assessed"


def trend_stats(test_code: str, points: Sequence[Point], cfg: TrendConfig = TrendConfig()) -> TrendStats:  # noqa: B008
    """Stats over ``points`` (any order; ties broken by input order). Floats are fine for the slope: these are
    descriptive statistics and no stored flag depends on them."""
    n = len(points)
    if n == 0:
        return TrendStats(n=0, direction="no_data")
    pts = sorted(points, key=lambda p: p.at)
    first, last = pts[0], pts[-1]
    abs_change = last.value - first.value
    pct_change = None if first.value == 0 else round(float(abs_change / first.value * 100), 1)
    xs = [(p.at - first.at).total_seconds() / SECONDS_PER_YEAR for p in pts]
    ys = [float(p.value) for p in pts]
    slope: float | None = None
    direction: Direction = "insufficient_data"
    rapid = False
    if n >= cfg.min_points and len(set(xs)) >= 2:
        mx, my = sum(xs) / n, sum(ys) / n
        den = sum((x - mx) ** 2 for x in xs)
        slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / den
        direction = direction_for(test_code, slope, cfg)
        rapid = test_code == "EGFR" and slope <= cfg.egfr_rapid_decline
    return TrendStats(
        n=n, direction=direction, first=first.value, last=last.value, abs_change=abs_change, pct_change=pct_change,
        slope_per_year=None if slope is None else round(slope, 2), rapid_decline=rapid,
        span_days=round((last.at - first.at).total_seconds() / 86400), first_at=first.at, last_at=last.at)
