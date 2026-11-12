from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, Field, field_validator

# at most 4 decimal places and 10 significant digits (LLD B4.1); a JSON number or a numeric string both parse
Value = Annotated[Decimal, Field(ge=0, allow_inf_nan=False, max_digits=10, decimal_places=4)]


class ResultIn(BaseModel):
    test_code: Annotated[str, Field(min_length=1, max_length=16)]
    value: Value
    unit: Annotated[str, Field(min_length=1, max_length=32)]


class ReportIn(BaseModel):
    collected_at: AwareDatetime
    lab_name: Annotated[str | None, Field(max_length=120)] = None
    notes: Annotated[str | None, Field(max_length=500)] = None
    results: Annotated[list[ResultIn], Field(min_length=1, max_length=8)]

    @field_validator("lab_name", "notes")
    @classmethod
    def _blank_is_none(cls, v: str | None) -> str | None:
        return (v.strip() or None) if v is not None else None


class CorrectionIn(BaseModel):
    value: Value
    unit: Annotated[str, Field(min_length=1, max_length=32)]
    reason: Annotated[str, Field(min_length=3, max_length=300)]


# ---- creation (LLD B7.2) -------------------------------------------------------------------------
class ReportOut(BaseModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    collected_at: datetime
    lab_name: str
    notes: str | None
    entered_by: uuid.UUID
    created_at: datetime


class CreatedResult(BaseModel):
    id: uuid.UUID
    test_code: str
    value: float                       # canonical unit
    unit: str
    value_original: float              # as entered
    unit_original: str                 # in the catalog's spelling
    ref_low: float | None              # snapshot at write time
    ref_high: float | None
    crit_low: float | None
    crit_high: float | None
    flag: str


class ReportSummary(BaseModel):
    n: int
    abnormal: int                      # low, high and both critical flags
    critical: int


class CreatedReport(BaseModel):
    report: ReportOut
    results: list[CreatedResult]
    summary: ReportSummary


# ---- correction (LLD B7.7) -----------------------------------------------------------------------
class CorrectedOut(BaseModel):
    id: uuid.UUID
    value: float
    flag: str
    superseded: bool = True


class CurrentResult(BaseModel):
    id: uuid.UUID
    supersedes_id: uuid.UUID
    test_code: str
    value: float
    unit: str
    value_original: float
    unit_original: str
    ref_low: float | None
    ref_high: float | None
    crit_low: float | None
    crit_high: float | None
    flag: str
    correction_reason: str


class Correction(BaseModel):
    corrected: CorrectedOut
    current: CurrentResult
    status_version: int


# ---- history item (replaced by the B7.3 shape in phase 8) ----------------------------------------
class ResultOut(BaseModel):
    id: uuid.UUID
    report_id: uuid.UUID
    patient_id: uuid.UUID
    test_code: str
    collected_at: datetime
    value: float                       # canonical unit
    unit: str
    value_original: float              # as entered
    unit_original: str
    ref_low: float | None              # snapshot at write time
    ref_high: float | None
    crit_low: float | None
    crit_high: float | None
    flag: str
    supersedes_id: uuid.UUID | None
    correction_reason: str | None
