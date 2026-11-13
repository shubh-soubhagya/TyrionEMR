from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ---- results history (LLD B7.3) ------------------------------------------------------------------
class HistoryItem(BaseModel):
    id: uuid.UUID
    report_id: uuid.UUID
    test_code: str
    test_name: str
    collected_at: datetime
    value: float                       # canonical unit
    unit: str
    value_original: float              # "Entered as" column: shown when unit_original differs from unit
    unit_original: str
    ref_low: float | None              # snapshot at write time
    ref_high: float | None
    flag: str
    lab_name: str
    is_correction: bool
    superseded: bool


class ResultsPage(BaseModel):
    items: list[HistoryItem]
    page: int
    size: int
    total: int


class InternalResultsPage(ResultsPage):
    """The internal mirror (LLD B7.8): capped by ``limit`` instead of paged, and told when the cap cut rows, so an
    AI tool can say the data was truncated instead of presenting a partial list as complete."""

    truncated: bool


# ---- trends (B7.4) -------------------------------------------------------------------------------
class TrendPoint(BaseModel):
    result_id: uuid.UUID
    collected_at: datetime
    value: float
    flag: str


class Reference(BaseModel):
    low: float | None
    high: float | None


class StageBand(BaseModel):
    code: str
    lower: int


class TrendSeries(BaseModel):
    test_code: str
    unit: str
    points: list[TrendPoint]
    stats: dict[str, Any]              # {"n": 0, "direction": "no_data"} when the window has no points
    reference: Reference | None        # from the latest point's snapshot; None when the window has no points
    stage_bands: list[StageBand] | None = None      # eGFR only


class TrendsOut(BaseModel):
    patient_id: uuid.UUID
    from_: datetime | None = Field(alias="from")
    to: datetime | None
    series: list[TrendSeries]

    model_config = ConfigDict(populate_by_name=True)


# ---- latest (B7.5) -------------------------------------------------------------------------------
class LatestResult(BaseModel):
    result_id: uuid.UUID
    report_id: uuid.UUID
    value: float
    flag: str
    collected_at: datetime
    ref_low: float | None
    ref_high: float | None


class LatestTile(BaseModel):
    test_code: str
    name: str
    canonical_unit: str
    result: LatestResult | None


class CkdBlock(BaseModel):
    egfr_category: str | None
    egfr_label: str | None
    egfr_value: float | None
    egfr_collected_at: datetime | None
    uacr_category: str | None
    uacr_label: str | None
    uacr_value: float | None
    uacr_collected_at: datetime | None


class Lt60Run(BaseModel):
    since: datetime
    n: int


class LatestOut(BaseModel):
    patient_id: uuid.UUID
    tests: list[LatestTile]
    ckd: CkdBlock
    has_critical: bool
    rapid_decline: bool
    last_result_at: datetime | None
    first_result_at: datetime | None
    egfr_lt60_run: Lt60Run | None
    status_version: int                # 0 when the patient has no results


# ---- batch summary (B7.6) ------------------------------------------------------------------------
class LatestEgfr(BaseModel):
    value: float
    flag: str
    collected_at: datetime


class SummaryItem(BaseModel):
    patient_id: uuid.UUID
    has_results: bool
    latest_egfr: LatestEgfr | None
    egfr_category: str | None
    egfr_direction: str | None
    spark: list[dict[str, Any]]
    has_critical: bool
    rapid_decline: bool
    last_result_at: datetime | None


class SummaryOut(BaseModel):
    items: list[SummaryItem]


# ---- internal bulk status (B7.9) -----------------------------------------------------------------
class StatusItem(BaseModel):
    patient_id: uuid.UUID
    latest: dict[str, dict[str, Any]]
    egfr_category: str | None
    uacr_category: str | None
    egfr_stats: dict[str, Any] | None
    creat_stats: dict[str, Any] | None
    has_critical: bool
    rapid_decline: bool
    result_count: int
    last_result_at: datetime | None
    first_result_at: datetime | None
    egfr_lt60_run: Lt60Run | None


class StatusPage(BaseModel):
    items: list[StatusItem]
    next_cursor: uuid.UUID | None
