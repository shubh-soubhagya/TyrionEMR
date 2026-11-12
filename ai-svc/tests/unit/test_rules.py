"""Rule engine tests (LLD B17.1): every rule has a positive, a negative and a boundary case."""
from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from uuid import uuid4

import pytest

from app.insights.rules.ckd_epi import age_on, ckd_epi_2021
from app.insights.rules.facts import EncFact, MedPastEnd, RuleConfig, Vitals
from app.insights.rules.gaps import RULE_CODES, evaluate, fmt_date
from tests.factories import NOW, TODAY, TZ, healthy, lab, run, trend, with_labs, with_latest

DEFAULT_CFG = RuleConfig()


def codes(f, cfg=DEFAULT_CFG):
    return [x.code for x in evaluate(f, today=TODAY, now=NOW, tz=TZ, cfg=cfg)]


def test_healthy_patient_has_no_findings():
    assert codes(healthy()) == []


def test_sixteen_rules_are_registered():
    assert len(RULE_CODES) == 16 and len(set(RULE_CODES)) == 16


# ---- CKD-EPI 2021 vectors (B4.4) --------------------------------------------------------------
@pytest.mark.parametrize(("scr", "age", "sex", "expected"), [
    (1.898, 67, "M", 38.2), (1.0, 34, "F", 75.8), (0.7, 45, "F", 108.6), (5.5, 61, "M", 11.1), (1.0, 55, "M", 88.9),
])
def test_ckd_epi_vectors(scr, age, sex, expected):
    assert ckd_epi_2021(scr, age, sex) == pytest.approx(expected, abs=0.1)


def test_age_on_collection_date_not_today():
    dob = date(1980, 6, 15)
    assert age_on(dob, date(2026, 6, 14)) == 45
    assert age_on(dob, date(2026, 6, 15)) == 46


# ---- rules 1-4: patient level -----------------------------------------------------------------
def test_allergy_unknown():
    assert codes(replace(healthy(), allergy_status="unknown")) == ["ALLERGY_STATUS_UNKNOWN"]
    assert codes(replace(healthy(), allergy_status="has_allergies")) == []


def test_no_primary_diagnosis():
    assert codes(replace(healthy(), has_active_primary=False)) == ["NO_PRIMARY_DIAGNOSIS"]


def test_no_medications_boundary():
    assert codes(replace(healthy(), medication_count=0)) == ["NO_MEDICATIONS_DOCUMENTED"]
    assert codes(replace(healthy(), medication_count=1)) == []


def test_no_labs_recorded_is_high_and_alone():
    f = replace(healthy(), labs=None)
    found = evaluate(f, today=TODAY, now=NOW, tz=TZ)
    assert [(x.code, x.severity) for x in found] == [("NO_LABS_RECORDED", "high")]


# ---- rule 5: recent labs, boundary at the threshold --------------------------------------------
def test_no_recent_labs_boundary():
    at = with_labs(healthy(), last_result_at=NOW - timedelta(days=180))
    over = with_labs(healthy(), last_result_at=NOW - timedelta(days=181))
    assert codes(at) == [] and codes(over) == ["NO_RECENT_LABS"]
    msg = evaluate(over, today=TODAY, now=NOW, tz=TZ)[0].message
    assert msg == "The most recent lab result is 181 days old (threshold 180 days)."


def test_no_recent_labs_threshold_is_configurable():
    f = with_labs(healthy(), last_result_at=NOW - timedelta(days=40))
    assert codes(f, RuleConfig(no_recent_labs_days=30)) == ["NO_RECENT_LABS"]


# ---- rule 6: one finding per missing required test ---------------------------------------------
def test_no_labs_for_test_one_per_test_in_order():
    f = healthy()
    assert f.labs is not None
    latest = {k: v for k, v in f.labs.latest.items() if k == "CREAT"}
    found = evaluate(with_labs(f, latest=latest), today=TODAY, now=NOW, tz=TZ)
    noted = [x for x in found if x.code == "NO_LABS_FOR_TEST"]
    assert [x.message for x in noted] == ["eGFR has never been recorded.",
                                          "Urine albumin-creatinine ratio has never been recorded."]


# ---- rule 7 ------------------------------------------------------------------------------------
@pytest.mark.parametrize(("n", "fires"), [(0, False), (1, True), (2, True), (3, False)])
def test_insufficient_trend_boundaries(n, fires):
    f = with_labs(healthy(), egfr=trend(n=n))
    assert (codes(f) == ["INSUFFICIENT_TREND_DATA"]) is fires


# ---- rules 8 and 9: per final encounter --------------------------------------------------------
def test_encounter_rules_are_per_encounter():
    a = EncFact(uuid4(), NOW - timedelta(days=30), False, True)
    b = EncFact(uuid4(), NOW - timedelta(days=20), False, False)
    c = EncFact(uuid4(), NOW - timedelta(days=10), True, True)
    f = replace(healthy(), final_encounters=(a, b, c))
    assert codes(f) == ["ENCOUNTER_NO_VITALS", "ENCOUNTER_NO_VITALS", "ENCOUNTER_NO_ASSESSMENT"]


# ---- rule 10: continuous trailing run, 90-day boundary -----------------------------------------
def _low_egfr(f, days):
    f = replace(f, established_stage=None)
    f = with_latest(f, EGFR=lab("EGFR", 52, "mL/min/1.73 m²", "low"))
    # category G3a would match no stage, but stage is None so rule 11 stays quiet
    return with_labs(f, egfr_category="G3a", egfr_lt60_run=run(days))


def test_no_established_stage_boundary_is_inclusive_at_90_days():
    assert "NO_ESTABLISHED_CKD_STAGE" in codes(_low_egfr(healthy(), 90))
    assert "NO_ESTABLISHED_CKD_STAGE" not in codes(_low_egfr(healthy(), 89))


def test_no_established_stage_needs_two_points_and_a_missing_stage():
    f = _low_egfr(healthy(), 200)
    assert "NO_ESTABLISHED_CKD_STAGE" not in codes(with_labs(f, egfr_lt60_run=run(200, n=1)))
    assert "NO_ESTABLISHED_CKD_STAGE" not in codes(replace(f, established_stage="G3a"))
    assert "NO_ESTABLISHED_CKD_STAGE" not in codes(with_labs(f, egfr_lt60_run=None))   # field not sent yet


def test_no_established_stage_not_when_latest_egfr_recovered():
    f = with_latest(replace(healthy(), established_stage=None), EGFR=lab("EGFR", 65, "mL/min/1.73 m²"))
    assert "NO_ESTABLISHED_CKD_STAGE" not in codes(with_labs(f, egfr_category="G2", egfr_lt60_run=run(300)))


# ---- rule 11 -----------------------------------------------------------------------------------
def test_stage_mismatch_is_high():
    f = with_labs(replace(healthy(), established_stage="G4"), egfr_category="G3b")
    found = evaluate(f, today=TODAY, now=NOW, tz=TZ)
    assert [(x.code, x.severity) for x in found if x.code == "CKD_STAGE_MISMATCH"] == [("CKD_STAGE_MISMATCH", "high")]
    assert "G4 does not match" in found[0].message and "(G3b, eGFR 90)" in found[0].message


def test_stage_match_or_missing_is_quiet():
    assert "CKD_STAGE_MISMATCH" not in codes(with_labs(replace(healthy(), established_stage="G3b"), egfr_category="G3b"))
    assert "CKD_STAGE_MISMATCH" not in codes(with_labs(healthy(), egfr_category=None))


# ---- rule 12 -----------------------------------------------------------------------------------
def test_lab_date_before_birth_and_in_future():
    dob = date(2026, 1, 1)
    early = with_labs(replace(healthy(), date_of_birth=dob), first_result_at=NOW - timedelta(days=400))
    assert "LAB_DATE_INVALID" in codes(early)
    future = with_labs(healthy(), last_result_at=NOW + timedelta(seconds=61))
    assert "LAB_DATE_INVALID" in codes(future)
    skew = with_labs(healthy(), last_result_at=NOW + timedelta(seconds=60))
    assert "LAB_DATE_INVALID" not in codes(skew)


def test_lab_date_rule_skips_when_first_result_not_sent():
    f = with_labs(replace(healthy(), date_of_birth=date(2026, 1, 1)), first_result_at=None)
    assert "LAB_DATE_INVALID" not in codes(f)


# ---- rule 13 -----------------------------------------------------------------------------------
def test_discordance_tolerance_boundary():
    # creat 1.0 mg/dL, age 45 on the collection date, male -> about 94
    est = ckd_epi_2021(1.0, age_on(date(1981, 3, 1), (NOW - timedelta(days=10)).date()), "M")
    inside = with_latest(healthy(), EGFR=lab("EGFR", round(est - 11.5), "mL/min/1.73 m²"))
    outside = with_latest(healthy(), EGFR=lab("EGFR", round(est - 13), "mL/min/1.73 m²"))
    assert "EGFR_CREATININE_DISCORDANT" not in codes(replace(inside, established_stage=None))
    assert "EGFR_CREATININE_DISCORDANT" in codes(outside)


def test_discordance_skipped_for_sex_o_and_different_reports():
    far = with_latest(healthy(), EGFR=lab("EGFR", 40, "mL/min/1.73 m²"))
    assert "EGFR_CREATININE_DISCORDANT" in codes(far)
    assert "EGFR_CREATININE_DISCORDANT" not in codes(replace(far, sex="O"))
    other = with_latest(healthy(), EGFR=lab("EGFR", 40, "mL/min/1.73 m²", report=uuid4()))
    assert "EGFR_CREATININE_DISCORDANT" not in codes(other)


# ---- rule 14 -----------------------------------------------------------------------------------
@pytest.mark.parametrize(("creat", "egfr", "fires"), [
    ("improving", "worsening", True), ("worsening", "improving", True),
    ("worsening", "worsening", False), ("stable", "worsening", False),
])
def test_direction_contradiction(creat, egfr, fires):
    f = with_labs(healthy(), creat=trend(direction=creat), egfr=trend(direction=egfr))
    assert ("DIRECTION_CONTRADICTION" in codes(f)) is fires


def test_direction_contradiction_needs_three_points():
    f = with_labs(healthy(), creat=trend(n=2, direction="improving"), egfr=trend(n=5, direction="worsening"))
    assert "DIRECTION_CONTRADICTION" not in codes(f)


# ---- rule 15 -----------------------------------------------------------------------------------
def test_med_past_end_date_boundary():
    gone = MedPastEnd(uuid4(), "Losartan", TODAY - timedelta(days=1))
    today = MedPastEnd(uuid4(), "Amlodipine", TODAY)
    found = evaluate(replace(healthy(), active_meds_past_end=(gone, today)), today=TODAY, now=NOW, tz=TZ)
    assert [x.message for x in found] == ["Losartan is marked active but its end date (11 Nov 2026) has passed."]


# ---- rule 16 (chart only) ----------------------------------------------------------------------
def test_implausible_vitals_only_when_vitals_present():
    bad = EncFact(uuid4(), NOW - timedelta(days=5), True, True, Vitals(systolic_bp=90, diastolic_bp=95))
    ok = EncFact(uuid4(), NOW - timedelta(days=5), True, True, Vitals(systolic_bp=120, diastolic_bp=80))
    none = EncFact(uuid4(), NOW - timedelta(days=5), True, True, None)
    assert codes(replace(healthy(), final_encounters=(bad,))) == ["IMPLAUSIBLE_VITALS"]
    assert codes(replace(healthy(), final_encounters=(ok, none))) == []


def test_dates_are_formatted_in_clinic_time_zone():
    # 21:00 UTC on 20 Oct is already 21 Oct in Asia/Kolkata
    from datetime import UTC, datetime
    assert fmt_date(datetime(2026, 10, 20, 21, 0, tzinfo=UTC), TZ) == "21 Oct 2026"


def test_findings_come_back_in_rule_order():
    f = replace(healthy(), allergy_status="unknown", medication_count=0, has_active_primary=False)
    assert codes(f) == ["ALLERGY_STATUS_UNKNOWN", "NO_PRIMARY_DIAGNOSIS", "NO_MEDICATIONS_DOCUMENTED"]
