"""Normalized facts the rules run on (LLD B4.1). Frozen dataclasses, no I/O.

Both upstream shapes (single-patient chart, bulk export) are converted into ``PatientFacts`` by
``adapters.py``, so the Overview, the worklist and the dashboard cannot disagree (AI-ADR-5).
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID


@dataclass(frozen=True)
class LatestLab:
    test_code: str
    value: Decimal
    unit: str
    flag: str
    collected_at: datetime
    report_id: UUID
    result_id: UUID


@dataclass(frozen=True)
class TrendFacts:
    n: int
    direction: str                       # worsening | improving | stable | insufficient_data | no_data | ...
    slope_per_year: float | None
    rapid_decline: bool
    first_at: datetime | None = None
    last_at: datetime | None = None


@dataclass(frozen=True)
class Run:
    """Trailing run of eGFR < 60 that ends at the latest eGFR."""
    since: datetime
    n: int


@dataclass(frozen=True)
class LabFacts:
    latest: Mapping[str, LatestLab]
    egfr_category: str | None
    uacr_category: str | None
    egfr: TrendFacts | None
    creat: TrendFacts | None
    has_critical: bool
    rapid_decline: bool
    first_result_at: datetime | None     # None when the lab service does not send it yet (B20.1)
    last_result_at: datetime
    egfr_lt60_run: Run | None            # None when absent or when the trailing run does not exist


@dataclass(frozen=True)
class Vitals:
    systolic_bp: int | None = None
    diastolic_bp: int | None = None
    heart_rate: int | None = None
    temperature_c: float | None = None
    weight_kg: float | None = None


@dataclass(frozen=True)
class EncFact:
    id: UUID
    encounter_date: datetime
    has_vitals: bool
    has_assessment_and_plan: bool
    vitals: Vitals | None = None         # only from the chart adapter (rule 16 is chart-only)


@dataclass(frozen=True)
class MedPastEnd:
    id: UUID
    name: str
    end_date: date


@dataclass(frozen=True)
class PatientFacts:
    patient_id: UUID
    sex: Literal["M", "F", "O"]
    date_of_birth: date
    allergy_status: Literal["unknown", "nka", "has_allergies"]
    established_stage: str | None
    has_active_primary: bool
    medication_count: int
    active_meds_past_end: tuple[MedPastEnd, ...]
    final_encounters: tuple[EncFact, ...]
    labs: LabFacts | None                # None = no lab results at all


@dataclass(frozen=True)
class Evidence:
    """Typed pointer to a record. The rule engine never builds ref strings (B4.2)."""
    type: Literal["patient", "lab", "encounter", "medication", "trend"]
    target_id: UUID | str | None
    on: date | None = None
    test_code: str | None = None         # lab and trend evidence


@dataclass(frozen=True)
class Finding:
    code: str
    severity: Literal["high", "medium", "low"]
    kind: Literal["missing", "inconsistent"]
    message: str
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True)
class Reason:
    severity: Literal["danger", "warn"]
    code: str
    text: str


@dataclass(frozen=True)
class Attention:
    rank: int                            # 0 critical result, 1 rapid decline, 2 high-severity gap
    reasons: tuple[Reason, ...]


@dataclass(frozen=True)
class RuleConfig:
    """Thresholds (B2). A change here must come with a RULES_VERSION bump."""
    no_recent_labs_days: int = 180
    egfr_discordance_tolerance: float = 12.0
    no_stage_lt60_min_days: int = 90
