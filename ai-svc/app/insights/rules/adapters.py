"""The two adapters that turn upstream shapes into ``PatientFacts`` (LLD B4.1, AI-ADR-5).

``from_chart`` feeds the Overview and the summary (one patient, three reads). ``from_bulk`` feeds the worklist and the
dashboard (two bulk pages). Both produce the same model, so one rule engine serves both and the parity test can
prove they agree.

Imports the upstream *models* (plain data classes), never a client: no I/O happens here.
"""
from __future__ import annotations

from datetime import date

from app.clients.models import Chart, ChartItem, LabSummary, Latest, StatusItem, Trends, TrendStatsIn
from app.insights.rules.facts import (
    EncFact,
    LabFacts,
    LatestLab,
    MedPastEnd,
    PatientFacts,
    Run,
    TrendFacts,
    Vitals,
)


def _trend(s: TrendStatsIn | None) -> TrendFacts | None:
    if s is None:
        return None
    return TrendFacts(n=s.n, direction=s.direction, slope_per_year=s.slope_per_year,
                      rapid_decline=s.rapid_decline, first_at=s.first_at, last_at=s.last_at)


def _lab_facts(src: LabSummary, egfr: TrendStatsIn | None, creat: TrendStatsIn | None) -> LabFacts | None:
    """None means 'no lab results at all' (every tile null), which is what NO_LABS_RECORDED tests."""
    if not src.latest or src.last_result_at is None:
        return None
    latest = {code: LatestLab(code, e.value, e.unit, e.flag, e.collected_at, e.report_id, e.result_id)
              for code, e in src.latest.items()}
    run = Run(src.egfr_lt60_run.since, src.egfr_lt60_run.n) if src.egfr_lt60_run else None
    return LabFacts(latest=latest, egfr_category=src.egfr_category, uacr_category=src.uacr_category,
                    egfr=_trend(egfr), creat=_trend(creat), has_critical=src.has_critical,
                    rapid_decline=src.rapid_decline, first_result_at=src.first_result_at,
                    last_result_at=src.last_result_at, egfr_lt60_run=run)


def from_chart(chart: Chart, latest: Latest, trends: Trends, *, today: date) -> PatientFacts:
    p = chart.patient
    vitals_by_enc = {e.id: e.vitals for e in chart.recent_encounters if e.vitals}
    finals = tuple(
        EncFact(e.id, e.encounter_date, e.has_vitals, e.has_assessment_and_plan,
                Vitals(**{k: v for k, v in vitals_by_enc[e.id].items() if k in Vitals.__dataclass_fields__})
                if e.id in vitals_by_enc else None)
        for e in chart.encounter_index if e.status == "final")
    past_end = tuple(MedPastEnd(m.id, m.name, m.end_date) for m in chart.medications
                     if m.status == "active" and m.end_date is not None and m.end_date < today)
    stats = {s.test_code: s.stats for s in trends.series}
    return PatientFacts(
        patient_id=p.id, sex=p.sex, date_of_birth=p.date_of_birth, allergy_status=p.allergy_status,
        established_stage=p.established_ckd_stage,
        has_active_primary=any(c.is_primary and c.status == "active" for c in chart.conditions),
        medication_count=len(chart.medications), active_meds_past_end=past_end, final_encounters=finals,
        labs=_lab_facts(latest, stats.get("EGFR"), stats.get("CREAT")))


def from_bulk(item: ChartItem, status: StatusItem | None) -> PatientFacts:
    """``status`` is None when lab-svc has no row for the patient: the patient counts as 'no labs' (B4.6)."""
    finals = tuple(EncFact(e.id, e.encounter_date, e.has_vitals, e.has_assessment_and_plan)
                   for e in item.final_encounters)
    return PatientFacts(
        patient_id=item.id, sex=item.sex, date_of_birth=item.date_of_birth, allergy_status=item.allergy_status,
        established_stage=item.established_ckd_stage, has_active_primary=item.has_active_primary,
        medication_count=item.medication_count,
        active_meds_past_end=tuple(MedPastEnd(m.id, m.name, m.end_date) for m in item.active_meds_past_end),
        final_encounters=finals,
        labs=_lab_facts(status, status.egfr_stats, status.creat_stats) if status else None)
