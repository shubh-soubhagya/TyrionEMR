"""Turns rule evidence (typed pointers) into refs the UI can open (LLD B4.2, B5.3, B12.6).

The ref grammar is the one the summary's RefBuilder uses (B5.3), so a gap shown on the Overview and the same gap
cited in a summary carry identical refs. Ordinals (``enc:N``, ``med:N``) follow the RefBuilder's ordering.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from uuid import UUID
from zoneinfo import ZoneInfo

from app.clients.models import Chart
from app.insights.rules.constants import TEST_NAMES
from app.insights.rules.facts import Evidence, Finding
from app.insights.rules.gaps import fmt_date

PATIENT_REFS = {"ALLERGY_STATUS_UNKNOWN": ("pt:allergy_status", "Allergy status")}


def encounter_order(chart: Chart) -> dict[UUID, int]:
    """enc:1..n, newest first across the whole encounter index."""
    ordered = sorted(chart.encounter_index, key=lambda e: (e.encounter_date, str(e.id)), reverse=True)
    return {e.id: i for i, e in enumerate(ordered, start=1)}


def medication_order(chart: Chart) -> dict[UUID, int]:
    """med:1..n, active first, then start date descending."""
    ordered = sorted(chart.medications,
                     key=lambda m: (m.status != "active", -(m.start_date or date.min).toordinal(), str(m.id)))
    return {m.id: i for i, m in enumerate(ordered, start=1)}


def hydrate(finding: Finding, ev: Evidence, *, tz: ZoneInfo, enc: dict[UUID, int],
            med: dict[UUID, int]) -> dict | None:
    """One evidence item as {ref, type, label, tab, target_id}; None when there is nothing to open."""
    target = str(ev.target_id) if ev.target_id else None
    if ev.type == "patient":
        ref = PATIENT_REFS.get(finding.code)
        if ref is None:
            return None
        return {"ref": ref[0], "type": "patient", "label": ref[1], "tab": "overview", "target_id": target}
    if ev.type == "lab" and ev.test_code and ev.on:
        return {"ref": f"lab:{ev.test_code}:{ev.on.isoformat()}", "type": "lab",
                "label": f"{TEST_NAMES.get(ev.test_code, ev.test_code)}, {fmt_date(ev.on, tz)}",
                "tab": "labs", "target_id": target}
    if ev.type == "trend" and ev.test_code:
        return {"ref": f"trend:{ev.test_code}", "type": "trend",
                "label": f"{TEST_NAMES.get(ev.test_code, ev.test_code)} trend", "tab": "labs", "target_id": None}
    if ev.type == "encounter" and isinstance(ev.target_id, UUID) and ev.target_id in enc and ev.on:
        return {"ref": f"enc:{enc[ev.target_id]}", "type": "encounter", "label": f"Encounter, {fmt_date(ev.on, tz)}",
                "tab": "encounters", "target_id": target}
    if ev.type == "medication" and isinstance(ev.target_id, UUID) and ev.target_id in med:
        return {"ref": f"med:{med[ev.target_id]}", "type": "medication", "label": "Medication",
                "tab": "medications", "target_id": target}
    return None


def hydrate_all(findings: Sequence[Finding], chart: Chart, tz: ZoneInfo) -> list[list[dict]]:
    enc, med = encounter_order(chart), medication_order(chart)
    return [[h for ev in f.evidence if (h := hydrate(f, ev, tz=tz, enc=enc, med=med))] for f in findings]
