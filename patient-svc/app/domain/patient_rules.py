"""Pure patient rules: no I/O, "today" is always passed in (computed in CLINIC_TZ by the caller, P-09)."""
from __future__ import annotations

from datetime import date

MAX_AGE_YEARS = 120
SETTABLE_ALLERGY_STATUSES = ("unknown", "nka")     # has_allergies is derived, never accepted (P-08)


def age_on(dob: date, today: date) -> int:
    """Whole years on ``today``. A 29 Feb birthday turns a year older on 1 Mar in non-leap years."""
    years = today.year - dob.year
    if (today.month, today.day) < (dob.month, dob.day):
        years -= 1
    return years


def validate_dob(dob: date, today: date) -> str | None:
    """The message to show, or None when the date of birth is acceptable."""
    if dob > today:
        return "Date of birth cannot be in the future."
    if age_on(dob, today) > MAX_AGE_YEARS:
        return "Check the date of birth. Age would exceed 120."
    return None


def allergy_status_after_removal(remaining_active: int, current: str) -> str:
    """Removing the last allergy returns to ``unknown`` (not ``nka``): removal is not confirmation (§13.7)."""
    if remaining_active > 0:
        return "has_allergies"
    return "unknown" if current == "has_allergies" else current


def can_set_allergy_status(requested: str, active_allergies: int) -> bool:
    return requested in SETTABLE_ALLERGY_STATUSES and active_allergies == 0
