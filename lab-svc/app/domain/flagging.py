"""Reference-range selection and abnormal flagging (HLD §6.2). Pure: no I/O."""
from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Final, Literal

Flag = Literal["normal", "low", "high", "critical_low", "critical_high", "unknown"]
ABNORMAL_FLAGS: Final[frozenset[str]] = frozenset({"low", "high", "critical_low", "critical_high"})


@dataclass(frozen=True, slots=True)
class RangeDef:
    test_code: str
    sex: str | None                     # "M" | "F" | None = any
    age_min: int | None
    age_max: int | None
    low: Decimal | None
    high: Decimal | None
    critical_low: Decimal | None
    critical_high: Decimal | None
    effective_from: date
    range_id: uuid.UUID | None = None      # the catalog row, kept in the result snapshot


def select_range(ranges: Iterable[RangeDef], test_code: str, sex: str | None, age: int | None,
                 on: date) -> RangeDef | None:
    """Picks the range that applies: test, then sex (specific over any), then age band (banded over open),
    then the latest ``effective_from`` not after ``on``. No match returns None, which flags as ``unknown``,
    never a silent ``normal``."""
    best: tuple[tuple[int, int, date], RangeDef] | None = None
    for r in ranges:
        if r.test_code != test_code or r.effective_from > on:
            continue
        if r.sex is not None and r.sex != sex:
            continue
        banded = r.age_min is not None or r.age_max is not None
        if banded:
            if age is None:
                continue
            if (r.age_min is not None and age < r.age_min) or (r.age_max is not None and age > r.age_max):
                continue
        key = (1 if r.sex is not None else 0, 1 if banded else 0, r.effective_from)
        if best is None or key > best[0]:
            best = (key, r)
    return best[1] if best else None


def age_on(dob: date, on: date) -> int:
    """Whole years of age on a date (negative when ``on`` precedes the birth date)."""
    return on.year - dob.year - ((on.month, on.day) < (dob.month, dob.day))


def flag_for(value: Decimal, rng: RangeDef | None) -> Flag:
    """Critical limits first, then the normal range. Limits are exclusive: a value equal to a limit is not
    beyond it."""
    if rng is None:
        return "unknown"
    if rng.critical_low is not None and value < rng.critical_low:
        return "critical_low"
    if rng.critical_high is not None and value > rng.critical_high:
        return "critical_high"
    if rng.low is not None and value < rng.low:
        return "low"
    if rng.high is not None and value > rng.high:
        return "high"
    return "normal"
