"""Pure domain rules (LLD §25.1): no I/O, no clock, no database."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.domain import encounter_rules as er
from app.domain.patient_rules import (
    age_on,
    allergy_status_after_removal,
    can_set_allergy_status,
    validate_dob,
)
from app.domain.problem_list import ConditionRef, infer_category, resolve_link
from app.domain.search import escape_like, order_by_sql, parse_query
from app.schemas.encounter import VitalsIn

TZ = "Asia/Kolkata"


# ---------------------------------- patient_rules -------------------------------------------------
def test_age_on_birthday_and_day_before():
    dob = date(1959, 4, 17)
    assert age_on(dob, date(2026, 4, 16)) == 66
    assert age_on(dob, date(2026, 4, 17)) == 67


def test_leap_day_birthday_in_non_leap_year():
    dob = date(2000, 2, 29)
    assert age_on(dob, date(2026, 2, 28)) == 25
    assert age_on(dob, date(2026, 3, 1)) == 26


def test_validate_dob():
    today = date(2026, 11, 11)
    assert validate_dob(today, today) is None
    assert validate_dob(date(2026, 11, 12), today) == "Date of birth cannot be in the future."
    assert validate_dob(date(1906, 11, 10), today) is None                    # exactly 120
    assert validate_dob(date(1905, 11, 11), today) == "Check the date of birth. Age would exceed 120."


def test_allergy_status_rules():
    assert allergy_status_after_removal(0, "has_allergies") == "unknown"       # removal is not confirmation
    assert allergy_status_after_removal(2, "has_allergies") == "has_allergies"
    assert allergy_status_after_removal(0, "nka") == "nka"
    assert can_set_allergy_status("nka", 0) and can_set_allergy_status("unknown", 0)
    assert not can_set_allergy_status("nka", 1)
    assert not can_set_allergy_status("has_allergies", 0)


# ---------------------------------- encounter_rules -----------------------------------------------
NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
DOB = date(1959, 4, 17)


def _enc(**kw):
    return er.EncounterFields(**{"encounter_date": NOW, **kw})


def test_future_visit_tolerance_is_60_seconds():
    assert er.validate_common(_enc(encounter_date=NOW + timedelta(seconds=59)), dob=DOB, now=NOW, tz_name=TZ) == []
    assert er.validate_common(_enc(encounter_date=NOW + timedelta(seconds=61)), dob=DOB, now=NOW, tz_name=TZ)


def test_follow_up_compares_in_clinic_timezone():
    # 20:00 UTC on the 10th is already the 11th in IST, so a follow-up on the 10th is BEFORE the visit
    visit = datetime(2026, 11, 10, 20, 0, tzinfo=UTC)
    early = _enc(encounter_date=visit, follow_up_date=date(2026, 11, 10))
    assert er.validate_common(early, dob=DOB, now=NOW, tz_name=TZ) == [
        ("follow_up_date", "Follow-up cannot be before the visit.")]
    assert er.validate_common(_enc(encounter_date=visit, follow_up_date=date(2026, 11, 11)),
                              dob=DOB, now=NOW, tz_name=TZ) == []


def test_visit_before_dob_rejected():
    old = _enc(encounter_date=datetime(1950, 1, 1, tzinfo=UTC))
    assert er.validate_common(old, dob=DOB, now=NOW, tz_name=TZ)


def test_finalizable_requires_three_fields_and_whitespace_is_empty():
    issues = er.validate_finalizable(_enc(chief_complaint="  ", assessment=None, plan="\n"))
    assert [f for f, _ in issues] == ["chief_complaint", "assessment", "plan"]
    assert er.validate_finalizable(_enc(chief_complaint="c", assessment="a", plan="p")) == []


def test_dedupe_symptoms():
    assert er.dedupe_symptoms(["Fatigue", " fatigue ", "Nausea", ""]) == ["Fatigue", "Nausea"]


# ---------------------------------- vitals --------------------------------------------------------
@pytest.mark.parametrize("field,ok,bad", [
    ("systolic_bp", (50, 300), (49, 301)), ("diastolic_bp", (20, 200), (19, 201)),
    ("heart_rate", (20, 300), (19, 301)), ("temperature_c", (30, 45), (29.9, 45.1)),
    ("weight_kg", (1, 500), (0.9, 500.1)),
])
def test_vitals_bounds(field, ok, bad):
    for v in ok:
        assert getattr(VitalsIn(**{field: v}), field) is not None
    for v in bad:
        with pytest.raises(ValidationError):
            VitalsIn(**{field: v})


def test_vitals_bp_order_rounding_and_empty():
    with pytest.raises(ValidationError):
        VitalsIn(systolic_bp=80, diastolic_bp=80)
    assert VitalsIn(systolic_bp=81, diastolic_bp=80).systolic_bp == 81
    assert str(VitalsIn(temperature_c=36.65).temperature_c) == "36.7"
    assert VitalsIn().is_empty() and VitalsIn(heart_rate=None).is_empty() and not VitalsIn(heart_rate=60).is_empty()


# ---------------------------------- problem list --------------------------------------------------
@pytest.mark.parametrize("icd,expected", [
    ("N18.32", "nephrology"), ("Q61.2", "nephrology"), ("M32.14", "nephrology"), ("E11.21", "nephrology"),
    ("I12.9", "nephrology"), ("I10", "comorbidity"), ("E78.5", "comorbidity"), ("D63.1", "comorbidity"),
    ("M32.9", "comorbidity"), (None, "comorbidity"),
])
def test_infer_category(icd, expected):
    assert infer_category(icd) == expected


def test_link_resolution_order():
    active = ConditionRef(1, "N18.32", "CKD 3b", "active")
    resolved = ConditionRef(2, "I10", "Hypertension", "resolved")
    nocode = ConditionRef(3, None, "Anaemia of CKD", "active")
    existing = [active, resolved, nocode]
    assert resolve_link("N18.32", "x", existing).kind == "linked"
    r = resolve_link("I10", "x", existing)
    assert (r.kind, r.condition) == ("reactivated", resolved)
    assert resolve_link(None, " anaemia OF ckd ", existing).kind == "linked"
    assert resolve_link("E11.21", "x", existing).kind == "added"
    assert resolve_link(None, "Something new", existing).kind == "added"
    assert resolve_link("N18.32", "x", [ConditionRef(9, "N18.32", "x", "resolved"), active]).condition == active


# ---------------------------------- search --------------------------------------------------------
@pytest.mark.parametrize("q,kind,value", [
    ("PT-000101", "mrn_digits", "000101"), ("pt101", "mrn_digits", "101"), ("101", "mrn_digits", "101"),
    ("PT-0001", "mrn_digits", "0001"),
])
def test_parse_mrn_forms(q, kind, value):
    spec = parse_query(q)
    assert (spec.kind, spec.value) == (kind, value)


def test_parse_name_tokens_escape_and_truncate():
    assert parse_query("Kulkarni   Ramesh").tokens == ("kulkarni", "ramesh")
    assert parse_query("100%_\\").tokens == ("100\\%\\_\\\\",)
    assert len(parse_query("a b c d e f g h").tokens) == 5
    assert parse_query("   ").kind == "none" and parse_query(None).kind == "none"
    assert escape_like("a%b_c\\") == "a\\%b\\_c\\\\"


def test_order_by_sql():
    assert order_by_sql("name", "asc") == "lower(f.last_name) ASC, lower(f.first_name) ASC, f.id"
    assert order_by_sql("age", "asc").startswith("f.date_of_birth DESC")
    assert order_by_sql("visit", "desc") == "lv.last_visit DESC NULLS LAST, f.id"
    with pytest.raises(KeyError):
        order_by_sql("egfr", "asc")
