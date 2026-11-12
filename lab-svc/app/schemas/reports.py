from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, Field, field_validator

Value = Annotated[Decimal, Field(ge=0, allow_inf_nan=False, max_digits=10, decimal_places=4)]


class ResultIn(BaseModel):
    test_code: Annotated[str, Field(min_length=1, max_length=16)]
    value: Value
    unit: Annotated[str, Field(min_length=1, max_length=32)]


class ReportIn(BaseModel):
    collected_at: AwareDatetime
    lab_name: Annotated[str | None, Field(max_length=120)] = None
    notes: Annotated[str | None, Field(max_length=2000)] = None
    results: Annotated[list[ResultIn], Field(min_length=1, max_length=8)]

    @field_validator("lab_name", "notes")
    @classmethod
    def _blank_is_none(cls, v: str | None) -> str | None:
        return (v.strip() or None) if v is not None else None


class CorrectionIn(BaseModel):
    value: Value
    unit: Annotated[str, Field(min_length=1, max_length=32)]
    reason: Annotated[str, Field(min_length=3, max_length=300)]


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


class ReportOut(BaseModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    collected_at: datetime
    lab_name: str | None
    notes: str | None
    created_at: datetime
    results: list[ResultOut]
