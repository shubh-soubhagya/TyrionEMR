"""Trend statistics (HLD §6.3). Pure: no I/O. Thresholds are configuration, not literals in the logic."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Final, Literal

Direction = Literal["improving", "stable", "worsening", "insufficient_data"]

MIN_POINTS: Final = 3                     # never extrapolate from two points
DAYS_PER_YEAR: Final = Decimal("365.25")


@dataclass(frozen=True, slots=True)
class DirectionRule:
    """``higher_is_worse``: creatinine rising is worsening; eGFR falling is worsening."""

    threshold: Decimal                    # slope per year
    higher_is_worse: bool


@dataclass(frozen=True, slots=True)
class TrendConfig:
    direction_rules: Mapping[str, DirectionRule]
    rapid_decline_slope: Decimal = Decimal(-5)      # KDIGO: worse than -5 mL/min/1.73m² per year
    rapid_decline_test: str = "EGFR"


DEFAULT_CONFIG: Final = TrendConfig(direction_rules={
    "EGFR": DirectionRule(Decimal(2), higher_is_worse=False),
    "CREAT": DirectionRule(Decimal("0.1"), higher_is_worse=True),
})


def _round(v: Decimal, places: int) -> float:
    return float(v.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP))


def slope_per_year(points: Sequence[tuple[datetime, Decimal]]) -> Decimal | None:
    """Ordinary least squares of value on days since the first point, scaled to a year.
    None when all points share one instant (slope undefined)."""
    t0 = points[0][0]
    xs = [Decimal(str((t - t0).total_seconds())) / Decimal(86400) for t, _ in points]
    ys = [v for _, v in points]
    n = Decimal(len(points))
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    return sxy / sxx * DAYS_PER_YEAR


def compute_stats(test_code: str, points: Sequence[tuple[datetime, Decimal]],
                  config: TrendConfig = DEFAULT_CONFIG) -> dict[str, Any] | None:
    """Stats for one test over the given points (any order). None for an empty series."""
    if not points:
        return None
    pts = sorted(points, key=lambda p: p[0])
    first, last = pts[0][1], pts[-1][1]
    slope = slope_per_year(pts) if len(pts) >= MIN_POINTS else None
    direction: Direction = "insufficient_data"
    rapid = False
    if slope is not None:
        rule = config.direction_rules.get(test_code)
        if rule is None:
            direction = "stable"
        else:
            worse = slope if rule.higher_is_worse else -slope      # positive = getting worse
            direction = ("worsening" if worse > rule.threshold else
                         "improving" if worse < -rule.threshold else "stable")
        rapid = test_code == config.rapid_decline_test and slope < config.rapid_decline_slope
    return {
        "n": len(pts),
        "first": float(first),
        "last": float(last),
        "abs_change": _round(last - first, 2),
        "pct_change": _round((last - first) / first * 100, 1) if first != 0 else None,
        "slope_per_year": _round(slope, 2) if slope is not None else None,
        "direction": direction,
        "rapid_decline": rapid,
        "span_days": (pts[-1][0] - pts[0][0]).days,
    }
