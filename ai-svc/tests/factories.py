"""Builders for rule tests: a healthy, complete patient that triggers no rule, then small overrides."""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from app.insights.rules.facts import (
    EncFact,
    LabFacts,
    LatestLab,
    PatientFacts,
    Run,
    TrendFacts,
)

TZ = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 11, 12, 6, 0, tzinfo=UTC)
TODAY = date(2026, 11, 12)
REPORT = UUID("00000000-0000-0000-0000-0000000000aa")


def lab(code: str, value: float | str, unit: str, flag: str = "normal", days_ago: int = 10,
        report: UUID = REPORT) -> LatestLab:
    return LatestLab(code, Decimal(str(value)), unit, flag, NOW - timedelta(days=days_ago), report, uuid4())


def trend(n: int = 5, direction: str = "stable", slope: float | None = 0.0, rapid: bool = False) -> TrendFacts:
    return TrendFacts(n, direction, slope, rapid, NOW - timedelta(days=700), NOW - timedelta(days=10))


def healthy_labs() -> LabFacts:
    # CKD-EPI 2021 for creat 1.0, 45 y, M is about 94, so eGFR 90 is within tolerance of 12
    latest = {
        "CREAT": lab("CREAT", 1.0, "mg/dL"), "EGFR": lab("EGFR", 90, "mL/min/1.73 m²"),
        "UACR": lab("UACR", 10, "mg/g"),
    }
    return LabFacts(latest=latest, egfr_category="G1", uacr_category="A1", egfr=trend(), creat=trend(),
                    has_critical=False, rapid_decline=False, first_result_at=NOW - timedelta(days=700),
                    last_result_at=NOW - timedelta(days=10), egfr_lt60_run=None)


def healthy() -> PatientFacts:
    enc = EncFact(uuid4(), NOW - timedelta(days=20), True, True)
    return PatientFacts(
        patient_id=uuid4(), sex="M", date_of_birth=date(1981, 3, 1), allergy_status="nka", established_stage="G1",
        has_active_primary=True, medication_count=2, active_meds_past_end=(), final_encounters=(enc,),
        labs=healthy_labs())


def with_labs(f: PatientFacts, **changes) -> PatientFacts:
    assert f.labs is not None
    return replace(f, labs=replace(f.labs, **changes))


def with_latest(f: PatientFacts, **latest: LatestLab) -> PatientFacts:
    assert f.labs is not None
    return with_labs(f, latest={**f.labs.latest, **latest})


def run(days: int, n: int = 3) -> Run:
    return Run(since=NOW - timedelta(days=10 + days), n=n)
