from __future__ import annotations

from pydantic import BaseModel


class AllowedUnit(BaseModel):
    unit: str
    factor: float                      # multiply by this to get the canonical unit


class ReferenceRangeOut(BaseModel):
    low: float | None
    high: float | None
    critical_low: float | None
    critical_high: float | None
    text: str                          # display text, e.g. "0.7–1.3", "≥ 90", "< 30"


class LabTestOut(BaseModel):
    code: str
    name: str
    canonical_unit: str
    allowed_units: list[AllowedUnit]
    decimals: int
    max_value: float
    reference_range: ReferenceRangeOut | None    # None: no range applies for this sex (never read as "normal")


class CatalogOut(BaseModel):
    sex: str | None
    tests: list[LabTestOut]
