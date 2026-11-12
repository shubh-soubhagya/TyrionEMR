"""The context packet: exactly what the model sees (LLD B5.2). PURE.

Only listed fields are copied (whitelist by construction), identifiers are never included (age instead of DOB, no
names, no MRN, no UUIDs), free text is scrubbed and truncated, drafts are counted but never shown (AI-ADR-10).
Absent data is explicit: empty lists stay ``[]``, ``unknown`` allergy status is sent as is.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from app.clients.models import Chart, Latest, LatestEntry, Trends, TrendStatsIn
from app.context.minimize import clean_text
from app.context.refs import RefBuilder
from app.insights.rules.ckd_epi import age_on
from app.insights.rules.constants import TEST_NAMES, TEST_ORDER
from app.insights.rules.facts import Finding

PACKET_VERSION = "cp-1"
TREND_TESTS = ("EGFR", "CREAT")


def num(v: float | Decimal | int | None) -> int | float | None:
    """Integral values become ints so 38, 38.0 and Decimal('38.0') serialize (and hash) identically."""
    if v is None:
        return None
    f = float(v)
    return int(f) if f == int(f) else round(f, 4)


def reference_text(low: Decimal | None, high: Decimal | None) -> str:
    if low is not None and high is not None:
        return f"{num(low)} – {num(high)}"
    if low is not None:
        return f"≥ {num(low)}"
    if high is not None:
        return f"≤ {num(high)}"
    return "Not documented"


def _day(dt: datetime, tz: ZoneInfo) -> str:
    return dt.astimezone(tz).date().isoformat()


def lab_entry(code: str, e: LatestEntry, b: RefBuilder) -> dict[str, Any]:
    name = TEST_NAMES.get(code, code)
    return {"ref": b.lab(code, name, e.collected_at, e.result_id), "test": code, "name": name, "value": num(e.value),
            "unit": e.unit, "flag": e.flag, "date": _day(e.collected_at, b.tz),
            "reference": reference_text(e.ref_low, e.ref_high)}


def trend_entry(code: str, s: TrendStatsIn, b: RefBuilder) -> dict[str, Any]:
    return {"ref": b.trend(code, TEST_NAMES.get(code, code)), "n": s.n, "first": num(s.first), "last": num(s.last),
            "abs_change": num(s.abs_change), "pct_change": num(s.pct_change), "slope_per_year": num(s.slope_per_year),
            "direction": s.direction, "rapid_decline": s.rapid_decline, "span_days": s.span_days,
            "first_date": _day(s.first_at, b.tz) if s.first_at else None,
            "last_date": _day(s.last_at, b.tz) if s.last_at else None}


def build_packet(chart: Chart, latest: Latest, trends: Trends, findings: Sequence[Finding], *, today: date,
                 builder: RefBuilder) -> dict[str, Any]:
    p = chart.patient
    b = builder
    history = {}
    for key, ref in (("past_medical_history", "pt:pmh"), ("family_history", "pt:fh"), ("social_history", "pt:sh")):
        text = clean_text(getattr(p, key))
        history[key] = {"ref": b.fixed(ref), "text": text} if text else None
    patient = {
        "age": age_on(p.date_of_birth, today), "sex": p.sex,
        "allergy_status": {"ref": b.fixed("pt:allergy_status"), "value": p.allergy_status},
        "established_ckd_stage": {"ref": b.fixed("pt:stage"), "value": p.established_ckd_stage},
        **history,
    }
    conditions = [{"ref": ref, "icd10": c.icd10_code, "description": c.description, "category": c.category,
                   "primary": c.is_primary, "status": c.status, "onset": c.onset_date}
                  for ref, c in b.conditions(chart.conditions)]
    medications = [{"ref": ref, "name": m.name, "dose": m.dose, "route": m.route, "frequency": m.frequency,
                    "status": m.status, "start": m.start_date.isoformat() if m.start_date else None,
                    "end": m.end_date.isoformat() if m.end_date else None}
                   for ref, m in b.medications(chart.medications)]
    allergies = [{"ref": ref, "allergen": a.allergen, "reaction": a.reaction, "severity": a.severity}
                 for ref, a in b.allergies(chart.allergies)]
    enc_refs = b.encounter_refs(chart.encounter_index)
    recent = []
    for e in sorted((e for e in chart.recent_encounters if e.status == "final"),
                    key=lambda e: e.encounter_date, reverse=True):
        recent.append({
            "ref": enc_refs.get(e.id), "date": _day(e.encounter_date, b.tz), "type": e.encounter_type,
            "chief_complaint": clean_text(e.chief_complaint), "symptoms": [clean_text(s) for s in e.symptoms if s],
            "examination": clean_text(e.examination_notes), "assessment": clean_text(e.assessment),
            "plan": clean_text(e.plan), "follow_up": e.follow_up_date, "vitals": e.vitals,
            "diagnoses": [{"icd10": d.icd10_code, "description": d.description} for d in e.diagnoses]})
    counts = chart.counts
    encounters = {"recent": [r for r in recent if r["ref"]], "final_count": counts.get("final_encounters", 0),
                  "draft_count": counts.get("drafts", 0)}

    ordered = sorted(latest.latest.items(), key=lambda kv: TEST_ORDER.get(kv[0], 99))
    labs: dict[str, Any] = {"latest": [lab_entry(c, e, b) for c, e in ordered], "ckd": None, "trends": {}}
    if ordered:
        egfr_cat = latest.egfr_category
        stage = p.established_ckd_stage
        labs["ckd"] = {"ref": b.fixed("ckd:latest"), "established": stage, "egfr_category": egfr_cat,
                       "uacr_category": latest.uacr_category,
                       "mismatch": bool(stage and egfr_cat and stage != egfr_cat)}
    stats = {s.test_code: s.stats for s in trends.series}
    for code in TREND_TESTS:
        s = stats.get(code)
        if s is not None and s.n > 0:
            labs["trends"][code] = trend_entry(code, s, b)
    rule_findings = [{"ref": b.gap(f.code, f.message), "code": f.code, "severity": f.severity, "kind": f.kind,
                      "message": f.message} for f in findings]
    return {"packet_version": PACKET_VERSION, "as_of": today.isoformat(), "patient": patient,
            "conditions": conditions, "medications": medications, "allergies": allergies,
            "encounters": encounters, "labs": labs, "rule_findings": rule_findings}
