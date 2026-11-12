from __future__ import annotations

import uuid

from pydantic import BaseModel


class UnitOut(BaseModel):
    unit: str
    factor: str                        # exact decimal as a string: multiply by it to get the canonical unit


class RangeOut(BaseModel):
    range_id: uuid.UUID | None
    sex: str | None = None             # None = any sex
    age_min: int | None = None
    age_max: int | None = None
    low: float | None
    high: float | None
    critical_low: float | None
    critical_high: float | None
    text: str                          # display text, e.g. "0.7–1.3", "≥ 90", "< 30"


class CatalogItem(BaseModel):
    code: str
    name: str
    canonical_unit: str
    decimals: int
    plausible_max: float
    display_order: int
    units: list[UnitOut]
    range: RangeOut | None             # with ?sex=: the range that applies today; None when none does (never "normal")
    ranges: list[RangeOut]             # without ?sex=: every range in force today; [] when sex was given


class CatalogOut(BaseModel):
    rules_version: str
    items: list[CatalogItem]
