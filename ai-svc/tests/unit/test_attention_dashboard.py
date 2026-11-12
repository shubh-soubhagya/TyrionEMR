"""Attention rule (B4.5) and dashboard aggregation (B4.6)."""
from __future__ import annotations

from dataclasses import replace

from app.insights.rules.attention import attention
from app.insights.rules.dashboard import PatientRow, build_dashboard
from app.insights.rules.facts import RuleConfig
from app.insights.rules.gaps import evaluate
from tests.factories import NOW, TODAY, TZ, healthy, lab, trend, with_labs, with_latest


def row(f, name="Pat One", mrn="PT-000101"):
    findings = tuple(evaluate(f, today=TODAY, now=NOW, tz=TZ, cfg=RuleConfig()))
    return PatientRow(f, mrn, name, 45, findings, attention(f, findings))


def test_healthy_patient_does_not_need_attention():
    assert row(healthy()).attention is None


def test_critical_result_reason_text_and_rank():
    f = with_labs(with_latest(healthy(), CREAT=lab("CREAT", 5.62, "mg/dL", "critical_high"),
                              K=lab("K", 6.2, "mmol/L", "critical_high")), has_critical=True)
    att = attention(f, [])
    assert att is not None and att.rank == 0
    assert [r.text for r in att.reasons] == ["Critical serum creatinine 5.62 mg/dL", "Critical potassium 6.2 mmol/L"]
    assert all(r.severity == "danger" for r in att.reasons)


def test_rapid_decline_reason():
    f = with_labs(healthy(), rapid_decline=True, egfr=trend(direction="worsening", slope=-7.34, rapid=True))
    att = attention(f, [])
    assert att is not None and att.rank == 1
    assert att.reasons[0].text == "eGFR falling 7.3 per year"


def test_high_gap_reason_has_no_trailing_period_and_at_most_two():
    f = replace(with_labs(healthy(), egfr_category="G3b"), established_stage="G4", labs=None)
    findings = evaluate(f, today=TODAY, now=NOW, tz=TZ)
    att = attention(f, findings)
    assert att is not None and att.rank == 2
    assert att.reasons[0].severity == "warn"
    assert att.reasons[0].text == "No laboratory results are on record for this patient"


def test_dashboard_kpis_distribution_and_ordering():
    crit = with_labs(with_latest(healthy(), K=lab("K", 6.2, "mmol/L", "critical_high")), has_critical=True)
    fast_a = with_labs(healthy(), rapid_decline=True, egfr_category="G4",
                       egfr=trend(direction="worsening", slope=-9.0, rapid=True))
    fast_b = with_labs(healthy(), rapid_decline=True, egfr_category="G3a",
                       egfr=trend(direction="worsening", slope=-6.0, rapid=True))
    no_labs = replace(healthy(), labs=None)
    rows = [row(fast_b, "Zed"), row(no_labs, "Ann"), row(fast_a, "Bob"), row(crit, "Cy"), row(healthy(), "Fine")]
    d = build_dashboard(rows, attention_limit=20, per_patient=2, total=8)
    assert d.kpis == {"patients": 5, "need_attention": 4, "critical_results": 1, "rapid_decline": 2}
    # critical first, then the most negative slope, then high-severity gaps
    assert [r.name for r in d.attention] == ["Cy", "Bob", "Zed", "Ann"]
    assert d.egfr_distribution == {"G1": 2, "G2": 0, "G3a": 1, "G3b": 0, "G4": 1, "G5": 0, "none": 1}


def test_attention_limit_caps_rows_but_not_kpi():
    rows = [row(replace(healthy(), labs=None), f"P{i:02d}") for i in range(30)]
    d = build_dashboard(rows, attention_limit=20, per_patient=2, total=8)
    assert d.kpis["need_attention"] == 30 and len(d.attention) == 20


def test_abnormal_results_cap_per_patient_and_total_and_exclude_unknown():
    f = with_latest(healthy(), K=lab("K", 6.2, "mmol/L", "critical_high", days_ago=3),
                    HB=lab("HB", 9.0, "g/dL", "low", days_ago=5), CA=lab("CA", 11.0, "mg/dL", "high", days_ago=1),
                    BUN=lab("BUN", 20, "mg/dL", "unknown"))
    d = build_dashboard([row(f)], attention_limit=20, per_patient=2, total=8)
    assert [(a.test, a.flag) for a in d.abnormal_results] == [("K", "critical_high"), ("CA", "high")]
    many = [row(with_latest(healthy(), HB=lab("HB", 9.0, "g/dL", "low")), f"P{i}") for i in range(12)]
    assert len(build_dashboard(many, attention_limit=20, per_patient=2, total=8).abnormal_results) == 8
