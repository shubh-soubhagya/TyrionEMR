"""The 16 gap and inconsistency rules (LLD B4.3). PURE: a function of ``PatientFacts``, the clinic date and the
thresholds. Order of evaluation is the order below; findings come back in that order."""
from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.insights.rules.ckd_epi import age_on, ckd_epi_2021
from app.insights.rules.constants import (
    FUTURE_SKEW_S,
    REQUIRED_TESTS,
    TEST_NAMES,
    TREND_MIN_POINTS,
    VITAL_RANGES,
)
from app.insights.rules.facts import (
    Evidence,
    Finding,
    PatientFacts,
    RuleConfig,
    Vitals,
)


def fmt_date(value: date | datetime, tz: ZoneInfo) -> str:
    """'d MMM yyyy' in the clinic time zone, for example '21 Oct 2026'."""
    d = value.astimezone(tz).date() if isinstance(value, datetime) else value
    return f"{d.day} {d:%b} {d.year}"


def _local_date(value: datetime, tz: ZoneInfo) -> date:
    return value.astimezone(tz).date()


def evaluate(f: PatientFacts, *, today: date, now: datetime, tz: ZoneInfo,
             cfg: RuleConfig = RuleConfig()) -> list[Finding]:  # noqa: B008 (frozen dataclass)
    out: list[Finding] = []
    for rule in _RULES:
        out.extend(rule(f, today, now, tz, cfg))
    return out


Rule = Callable[[PatientFacts, date, datetime, ZoneInfo, RuleConfig], list[Finding]]


def _patient(f: PatientFacts) -> Evidence:
    return Evidence("patient", f.patient_id)


# 1
def _allergy_unknown(f, today, now, tz, cfg):
    if f.allergy_status != "unknown":
        return []
    return [Finding("ALLERGY_STATUS_UNKNOWN", "medium", "missing",
                    'Allergy status is unknown. "Unknown" is not the same as "no known allergies".', (_patient(f),))]


# 2
def _no_primary(f, today, now, tz, cfg):
    if f.has_active_primary:
        return []
    return [Finding("NO_PRIMARY_DIAGNOSIS", "medium", "missing",
                    "No active primary diagnosis is recorded.", (_patient(f),))]


# 3
def _no_meds(f, today, now, tz, cfg):
    if f.medication_count != 0:
        return []
    return [Finding("NO_MEDICATIONS_DOCUMENTED", "low", "missing",
                    'No medications are documented, so "takes none" cannot be told apart from "not recorded".',
                    (_patient(f),))]


# 4
def _no_labs(f, today, now, tz, cfg):
    if f.labs is not None:
        return []
    return [Finding("NO_LABS_RECORDED", "high", "missing", "No laboratory results are on record for this patient.")]


def _latest_result_evidence(f: PatientFacts) -> tuple[Evidence, ...]:
    assert f.labs is not None
    if not f.labs.latest:
        return ()
    newest = max(f.labs.latest.values(), key=lambda r: r.collected_at)
    return (Evidence("lab", newest.result_id, _local_date(newest.collected_at, ZoneInfo("UTC")), newest.test_code),)


# 5
def _no_recent_labs(f, today, now, tz, cfg):
    if f.labs is None:
        return []
    days = (today - _local_date(f.labs.last_result_at, tz)).days
    if days <= cfg.no_recent_labs_days:
        return []
    return [Finding("NO_RECENT_LABS", "medium", "missing",
                    f"The most recent lab result is {days} days old (threshold {cfg.no_recent_labs_days} days).",
                    _latest_result_evidence(f))]


# 6
def _no_labs_for_test(f, today, now, tz, cfg):
    if f.labs is None:
        return []
    return [Finding("NO_LABS_FOR_TEST", "low", "missing", f"{TEST_NAMES[code]} has never been recorded.")
            for code in REQUIRED_TESTS if code not in f.labs.latest]


# 7
def _insufficient_trend(f, today, now, tz, cfg):
    if f.labs is None or f.labs.egfr is None:
        return []
    n = f.labs.egfr.n
    if not 0 < n < TREND_MIN_POINTS:
        return []
    return [Finding("INSUFFICIENT_TREND_DATA", "low", "missing",
                    f"Only {n} eGFR result(s) on record; a trend needs at least {TREND_MIN_POINTS}.",
                    (Evidence("trend", None, test_code="EGFR"),))]


# 8
def _enc_no_vitals(f, today, now, tz, cfg):
    return [Finding("ENCOUNTER_NO_VITALS", "low", "missing",
                    f"Final encounter on {fmt_date(e.encounter_date, tz)} has no vitals recorded.",
                    (Evidence("encounter", e.id, _local_date(e.encounter_date, tz)),))
            for e in f.final_encounters if not e.has_vitals]


# 9
def _enc_no_plan(f, today, now, tz, cfg):
    return [Finding("ENCOUNTER_NO_ASSESSMENT", "medium", "missing",
                    f"Final encounter on {fmt_date(e.encounter_date, tz)} is missing an assessment or plan.",
                    (Evidence("encounter", e.id, _local_date(e.encounter_date, tz)),))
            for e in f.final_encounters if not e.has_assessment_and_plan]


# 10  (continuous trailing run: a deliberate, documented deviation from the prototype, B4.3)
def _no_established_stage(f, today, now, tz, cfg):
    if f.established_stage is not None or f.labs is None:
        return []
    egfr = f.labs.latest.get("EGFR")
    run = f.labs.egfr_lt60_run
    if egfr is None or run is None or egfr.value >= 60 or run.n < 2:
        return []
    if egfr.collected_at - run.since < timedelta(days=cfg.no_stage_lt60_min_days):
        return []
    return [Finding("NO_ESTABLISHED_CKD_STAGE", "medium", "missing",
                    "eGFR has been below 60 for over 3 months but no established CKD stage is recorded.",
                    (Evidence("lab", None, _local_date(run.since, tz), "EGFR"),))]


# 11
def _stage_mismatch(f, today, now, tz, cfg):
    if f.established_stage is None or f.labs is None or f.labs.egfr_category is None:
        return []
    if f.established_stage == f.labs.egfr_category:
        return []
    egfr = f.labs.latest.get("EGFR")
    value = f"{egfr.value:.0f}" if egfr else "not documented"
    return [Finding("CKD_STAGE_MISMATCH", "high", "inconsistent",
                    f"Established CKD stage {f.established_stage} does not match the eGFR category of the latest "
                    f"result ({f.labs.egfr_category}, eGFR {value}).",
                    (Evidence("lab", egfr.result_id, _local_date(egfr.collected_at, tz), "EGFR"),) if egfr else ())]


# 12
def _lab_date_invalid(f, today, now, tz, cfg):
    if f.labs is None:
        return []
    before_birth = f.labs.first_result_at is not None and _local_date(f.labs.first_result_at, tz) < f.date_of_birth
    in_future = f.labs.last_result_at > now + timedelta(seconds=FUTURE_SKEW_S)
    if not (before_birth or in_future):
        return []
    return [Finding("LAB_DATE_INVALID", "high", "inconsistent",
                    "A lab result is dated before the date of birth (or in the future). Check the record.",
                    (_patient(f),))]


# 13
def _egfr_creat_discordant(f, today, now, tz, cfg):
    if f.labs is None or f.sex not in ("M", "F"):
        return []
    egfr, creat = f.labs.latest.get("EGFR"), f.labs.latest.get("CREAT")
    if egfr is None or creat is None or egfr.report_id != creat.report_id:
        return []
    age = age_on(f.date_of_birth, _local_date(creat.collected_at, tz))
    estimate = ckd_epi_2021(float(creat.value), age, f.sex)
    if abs(estimate - float(egfr.value)) <= cfg.egfr_discordance_tolerance:
        return []
    return [Finding("EGFR_CREATININE_DISCORDANT", "medium", "inconsistent",
                    f"Reported eGFR {egfr.value:.0f} differs from the CKD-EPI 2021 estimate ({estimate:.0f}) "
                    f"computed from creatinine {creat.value:.2f} mg/dL.",
                    (Evidence("lab", egfr.result_id, _local_date(egfr.collected_at, tz), "EGFR"),
                     Evidence("lab", creat.result_id, _local_date(creat.collected_at, tz), "CREAT")))]


# 14
def _direction_contradiction(f, today, now, tz, cfg):
    if f.labs is None or f.labs.egfr is None or f.labs.creat is None:
        return []
    e, c = f.labs.egfr, f.labs.creat
    if e.n < TREND_MIN_POINTS or c.n < TREND_MIN_POINTS:
        return []
    contradicts = ((c.direction == "improving" and e.direction == "worsening")
                   or (c.direction == "worsening" and e.direction == "improving"))
    if not contradicts:
        return []
    return [Finding("DIRECTION_CONTRADICTION", "medium", "inconsistent",
                    "Creatinine and eGFR are trending in clinically incompatible directions.",
                    (Evidence("trend", None, test_code="EGFR"), Evidence("trend", None, test_code="CREAT")))]


# 15
def _med_past_end(f, today, now, tz, cfg):
    return [Finding("ACTIVE_MED_PAST_END_DATE", "low", "inconsistent",
                    f"{m.name} is marked active but its end date ({fmt_date(m.end_date, tz)}) has passed.",
                    (Evidence("medication", m.id, m.end_date),))
            for m in f.active_meds_past_end if m.end_date < today]


def _implausible_fields(v: Vitals) -> list[str]:
    bad = [name for name, (lo, hi) in VITAL_RANGES.items()
           if (val := getattr(v, name)) is not None and not lo <= val <= hi]
    if v.systolic_bp is not None and v.diastolic_bp is not None and v.systolic_bp <= v.diastolic_bp:
        bad.append("blood pressure order")
    return bad


# 16 (chart adapter only: the bulk export carries no vitals)
def _implausible_vitals(f, today, now, tz, cfg):
    out = []
    for e in f.final_encounters:
        if e.vitals is None:
            continue
        bad = _implausible_fields(e.vitals)
        if bad:
            out.append(Finding("IMPLAUSIBLE_VITALS", "low", "inconsistent",
                               f"Encounter on {fmt_date(e.encounter_date, tz)} has implausible vitals "
                               f"({', '.join(bad)}).",
                               (Evidence("encounter", e.id, _local_date(e.encounter_date, tz)),)))
    return out


_RULES: tuple[Rule, ...] = (
    _allergy_unknown, _no_primary, _no_meds, _no_labs, _no_recent_labs, _no_labs_for_test, _insufficient_trend,
    _enc_no_vitals, _enc_no_plan, _no_established_stage, _stage_mismatch, _lab_date_invalid,
    _egfr_creat_discordant, _direction_contradiction, _med_past_end, _implausible_vitals,
)
RULE_CODES = (
    "ALLERGY_STATUS_UNKNOWN", "NO_PRIMARY_DIAGNOSIS", "NO_MEDICATIONS_DOCUMENTED", "NO_LABS_RECORDED",
    "NO_RECENT_LABS", "NO_LABS_FOR_TEST", "INSUFFICIENT_TREND_DATA", "ENCOUNTER_NO_VITALS",
    "ENCOUNTER_NO_ASSESSMENT", "NO_ESTABLISHED_CKD_STAGE", "CKD_STAGE_MISMATCH", "LAB_DATE_INVALID",
    "EGFR_CREATININE_DISCORDANT", "DIRECTION_CONTRADICTION", "ACTIVE_MED_PAST_END_DATE", "IMPLAUSIBLE_VITALS",
)
