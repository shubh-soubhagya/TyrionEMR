"""The ``facts`` and ``gaps`` blocks of a summary (LLD B12.4): computed by the system, never by the model.

Pure: lab-svc's flags, categories and trend statistics are copied as they are; the rule findings come from the
engine. The LLM only narrates these (D3, D4, D5).
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.clients.models import Chart, Latest, Trends
from app.context.packet import TREND_TESTS, num
from app.context.refs import RefBuilder, RefEntry
from app.insights.hydrate import hydrate_all
from app.insights.rules.constants import ABNORMAL_FLAGS, RULES_VERSION, TEST_NAMES, TEST_ORDER
from app.insights.rules.facts import Finding


def build_facts(chart: Chart, latest: Latest, trends: Trends, builder: RefBuilder) -> dict[str, Any]:
    stage = chart.patient.established_ckd_stage
    egfr = latest.latest.get("EGFR")
    ckd = None
    if latest.latest:
        ckd = {"established": stage, "egfr_category": latest.egfr_category, "uacr_category": latest.uacr_category,
               "mismatch": bool(stage and latest.egfr_category and stage != latest.egfr_category),
               "egfr_value": num(egfr.value) if egfr else None,
               "egfr_collected_at": egfr.collected_at.isoformat() if egfr else None, "ref": "ckd:latest"}
    abnormal = [
        {"test": code, "name": TEST_NAMES.get(code, code), "value": num(e.value), "unit": e.unit, "flag": e.flag,
         "collected_at": e.collected_at.isoformat(),
         "ref": builder.lab(code, TEST_NAMES.get(code, code), e.collected_at, e.result_id)}
        for code, e in sorted(latest.latest.items(), key=lambda kv: TEST_ORDER.get(kv[0], 99))
        if e.flag in ABNORMAL_FLAGS]
    trend_block = {}
    for s in trends.series:
        if s.test_code in TREND_TESTS and s.stats is not None and s.stats.n > 0:
            st = s.stats
            trend_block[s.test_code] = {
                "n": st.n, "first": num(st.first), "last": num(st.last), "abs_change": num(st.abs_change),
                "pct_change": num(st.pct_change), "slope_per_year": num(st.slope_per_year), "direction": st.direction,
                "rapid_decline": st.rapid_decline, "span_days": st.span_days, "ref": f"trend:{s.test_code}"}
    return {"provenance": "system_computed_from_patient_records", "ckd": ckd, "abnormal_results": abnormal,
            "trends": trend_block}


def build_gaps(findings: Sequence[Finding], chart: Chart, builder: RefBuilder) -> dict[str, Any]:
    """Findings with evidence refs. Each finding's own ref (``gap:CODE``) was assigned by the packet builder, in
    the same order, so a gap shown here and cited by the model carry the same ref."""
    evidence = hydrate_all(findings, chart, builder.tz)
    out = []
    seen: dict[str, int] = {}
    for f, ev in zip(findings, evidence, strict=True):
        n = seen[f.code] = seen.get(f.code, 0) + 1
        refs = []
        for h in ev:
            builder.index.add(h["ref"], RefEntry(h["type"], h["target_id"], h["label"], h["tab"]))
            refs.append(h["ref"])
        out.append({"code": f.code, "severity": f.severity, "kind": f.kind, "message": f.message,
                    "evidence_refs": refs, "ref": f"gap:{f.code}" if n == 1 else f"gap:{f.code}#{n}"})
    return {"provenance": "rule_engine", "rules_version": RULES_VERSION, "findings": out}
