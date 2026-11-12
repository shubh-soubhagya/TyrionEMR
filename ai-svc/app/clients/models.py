"""Upstream response models (LLD B14). ``extra="ignore"``: an additive upstream change never breaks ai-svc, while a
removed or renamed field fails loudly (here and in the contract tests, B17.7)."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict


class Up(BaseModel):
    model_config = ConfigDict(extra="ignore")


def _category_code(v: Any) -> Any:
    """lab-svc sends a category as {"code", "label"} on /latest and as a bare code on /status."""
    return v.get("code") if isinstance(v, dict) else v


Category = Annotated[str | None, BeforeValidator(_category_code)]


# ---- patient-svc ------------------------------------------------------------------------------
class PatientBasic(Up):
    id: UUID
    sex: Literal["M", "F", "O"]
    date_of_birth: date


class ChartPatient(Up):
    id: UUID
    age: int
    sex: Literal["M", "F", "O"]
    date_of_birth: date
    allergy_status: Literal["unknown", "nka", "has_allergies"]
    established_ckd_stage: str | None = None
    past_medical_history: str | None = None
    family_history: str | None = None
    social_history: str | None = None


class ChartCondition(Up):
    id: UUID
    is_primary: bool
    status: str
    icd10_code: str | None = None
    description: str = ""
    category: str = "comorbidity"
    onset_date: str | None = None


class ChartMedication(Up):
    id: UUID
    name: str
    dose: str = ""
    route: str = "other"
    frequency: str = ""
    start_date: date | None = None
    end_date: date | None = None
    status: str


class ChartAllergy(Up):
    id: UUID
    allergen: str
    reaction: str | None = None
    severity: str = "mild"


class ChartDiagnosis(Up):
    icd10_code: str | None = None
    description: str = ""


class ChartEncounter(Up):
    id: UUID
    encounter_date: datetime
    status: str
    vitals: dict[str, Any] | None = None
    encounter_type: str = "follow_up"
    chief_complaint: str | None = None
    symptoms: list[str] = []
    examination_notes: str | None = None
    assessment: str | None = None
    plan: str | None = None
    follow_up_date: str | None = None
    diagnoses: list[ChartDiagnosis] = []


class EncounterIndex(Up):
    id: UUID
    encounter_date: datetime
    status: str
    has_vitals: bool
    has_assessment_and_plan: bool


class Chart(Up):
    patient: ChartPatient
    conditions: list[ChartCondition] = []
    medications: list[ChartMedication] = []
    allergies: list[ChartAllergy] = []
    counts: dict[str, int] = {}
    recent_encounters: list[ChartEncounter] = []
    encounter_index: list[EncounterIndex] = []


class MedPastEndIn(Up):
    id: UUID
    name: str
    end_date: date


class FinalEncounterIn(Up):
    id: UUID
    encounter_date: datetime
    has_vitals: bool
    has_assessment_and_plan: bool


class ChartItem(Up):
    id: UUID
    mrn: str
    first_name: str
    last_name: str
    date_of_birth: date
    age: int
    sex: Literal["M", "F", "O"]
    allergy_status: Literal["unknown", "nka", "has_allergies"]
    established_ckd_stage: str | None = None
    has_active_primary: bool
    medication_count: int
    active_meds_past_end: list[MedPastEndIn] = []
    final_encounters: list[FinalEncounterIn] = []


class ChartsPage(Up):
    items: list[ChartItem]
    next_cursor: UUID | None = None


# ---- lab-svc ----------------------------------------------------------------------------------
class LatestEntry(Up):
    result_id: UUID
    report_id: UUID
    value: Decimal
    unit: str
    flag: str
    collected_at: datetime
    ref_low: Decimal | None = None
    ref_high: Decimal | None = None


class RunIn(Up):
    since: datetime
    n: int


class TrendStatsIn(Up):
    n: int
    direction: str
    first: float | None = None
    last: float | None = None
    abs_change: float | None = None
    pct_change: float | None = None
    span_days: int | None = None
    slope_per_year: float | None = None
    rapid_decline: bool = False
    first_at: datetime | None = None
    last_at: datetime | None = None


class LabSummary(Up):
    """Fields shared by /latest and a /status item."""
    latest: dict[str, LatestEntry] = {}
    egfr_category: Category = None
    uacr_category: Category = None
    has_critical: bool = False
    rapid_decline: bool = False
    last_result_at: datetime | None = None
    # B20.1: requested from lab-svc. Optional until lab-svc sends them (rules 10 and 12 skip without them).
    first_result_at: datetime | None = None
    egfr_lt60_run: RunIn | None = None


class Latest(LabSummary):
    patient_id: UUID


class TrendPointIn(Up):
    result_id: UUID | None = None
    collected_at: datetime
    value: float
    flag: str = "normal"
    ref_low: float | None = None
    ref_high: float | None = None


class TrendSeries(Up):
    test_code: str
    unit: str = ""
    stats: TrendStatsIn | None = None
    points: list[TrendPointIn] = []


class Trends(Up):
    patient_id: UUID
    series: list[TrendSeries] = []


class StatusItem(LabSummary):
    patient_id: UUID
    egfr_stats: TrendStatsIn | None = None
    creat_stats: TrendStatsIn | None = None


class StatusPage(Up):
    items: list[StatusItem]
    next_cursor: UUID | None = None
