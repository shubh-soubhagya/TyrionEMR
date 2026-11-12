from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.schemas.reports import ResultOut


class ResultsPage(BaseModel):
    items: list[ResultOut]
    total: int
    page: int
    size: int


class TrendPoint(BaseModel):
    collected_at: datetime
    value: float
    flag: str
    ref_low: float | None
    ref_high: float | None


class TrendSeries(BaseModel):
    test_code: str
    unit: str
    points: list[TrendPoint]
    stats: dict[str, Any] | None        # None when there are no points


class TrendsOut(BaseModel):
    patient_id: uuid.UUID
    series: list[TrendSeries]


class CategoryOut(BaseModel):
    code: str
    label: str | None = None


class LatestOut(BaseModel):
    patient_id: uuid.UUID
    latest: dict[str, dict[str, Any]]            # test code -> latest result; empty when nothing is documented
    egfr_category: CategoryOut | None
    uacr_category: CategoryOut | None
    has_critical: bool
    rapid_decline: bool
    last_result_at: datetime | None


class SummaryItem(BaseModel):
    patient_id: uuid.UUID
    has_data: bool
    latest_egfr: dict[str, Any] | None
    egfr_category: str | None
    egfr_spark: list[dict[str, Any]]
    has_critical: bool
    rapid_decline: bool
    last_result_at: datetime | None


class SummaryOut(BaseModel):
    items: list[SummaryItem]


class StatusItem(BaseModel):
    patient_id: uuid.UUID
    latest: dict[str, dict[str, Any]]
    egfr_category: str | None
    uacr_category: str | None
    egfr_stats: dict[str, Any] | None
    creat_stats: dict[str, Any] | None
    has_critical: bool
    rapid_decline: bool
    last_result_at: datetime | None


class StatusPage(BaseModel):
    items: list[StatusItem]
    next_cursor: uuid.UUID | None
