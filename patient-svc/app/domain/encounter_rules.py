"""Pure encounter rules (LLD §11.8, §13.4). All "today"/"now" values are passed in so tests need no clock.

The functions work on a plain ``EncounterFields`` snapshot, so the same checks run on a create body, on a
stored draft merged with a PATCH, and on the stored row at finalize time.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

FUTURE_TOLERANCE = timedelta(seconds=60)

Issues = list[tuple[str, str]]


@dataclass(frozen=True)
class EncounterFields:
    encounter_date: datetime
    chief_complaint: str | None = None
    assessment: str | None = None
    plan: str | None = None
    follow_up_date: date | None = None
    symptoms: tuple[str, ...] = field(default_factory=tuple)


def to_clinic_date(moment: datetime, tz_name: str) -> date:
    return moment.astimezone(ZoneInfo(tz_name)).date()


def blank(value: str | None) -> bool:
    return value is None or not value.strip()


def validate_common(enc: EncounterFields, *, dob: date, now: datetime, tz_name: str) -> Issues:
    issues: Issues = []
    if enc.encounter_date > now + FUTURE_TOLERANCE:
        issues.append(("encounter_date", "Visit date cannot be in the future."))
    visit_day = to_clinic_date(enc.encounter_date, tz_name)
    if visit_day < dob:
        issues.append(("encounter_date", "Visit date cannot be before the date of birth."))
    if enc.follow_up_date is not None and enc.follow_up_date < visit_day:
        issues.append(("follow_up_date", "Follow-up cannot be before the visit."))
    return issues


def validate_finalizable(enc: EncounterFields) -> Issues:
    """Whitespace-only counts as empty."""
    issues: Issues = []
    if blank(enc.chief_complaint):
        issues.append(("chief_complaint", "Chief complaint is required to finalize."))
    if blank(enc.assessment):
        issues.append(("assessment", "Assessment is required to finalize."))
    if blank(enc.plan):
        issues.append(("plan", "Plan is required to finalize."))
    return issues


def dedupe_symptoms(symptoms: list[str]) -> list[str]:
    """Trim, drop blanks, de-duplicate case-insensitively keeping the first spelling."""
    seen: set[str] = set()
    out: list[str] = []
    for s in symptoms:
        t = s.strip()
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out
