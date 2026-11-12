"""Dashboard and worklist aggregation (LLD B4.6). PURE: rows in, plain data out. Names and MRNs ride along in
``PatientRow`` because the dashboard shows them; nothing here stores or logs them."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.insights.rules.attention import fmt_value
from app.insights.rules.constants import ABNORMAL_FLAGS, EGFR_GROUPS, TEST_NAMES
from app.insights.rules.facts import Attention, Finding, PatientFacts


@dataclass(frozen=True)
class PatientRow:
    facts: PatientFacts
    mrn: str
    name: str
    age: int
    findings: tuple[Finding, ...]
    attention: Attention | None


@dataclass(frozen=True)
class AttentionRow:
    patient_id: UUID
    mrn: str
    name: str
    age: int
    rank: int
    reasons: tuple


@dataclass(frozen=True)
class AbnormalResult:
    patient_id: UUID
    name: str
    mrn: str
    test: str
    test_name: str
    value: float
    value_text: str
    unit: str
    flag: str
    collected_at: datetime
    result_id: UUID


@dataclass(frozen=True)
class Dashboard:
    kpis: dict[str, int]
    attention: tuple[AttentionRow, ...]
    egfr_distribution: dict[str, int]
    abnormal_results: tuple[AbnormalResult, ...]


def _slope(row: PatientRow) -> float:
    egfr = row.facts.labs.egfr if row.facts.labs else None
    return egfr.slope_per_year if egfr and egfr.slope_per_year is not None else 0.0


def attention_rows(rows: Sequence[PatientRow]) -> list[AttentionRow]:
    """Ordered by rank (critical, rapid decline, high-severity gap), then the most negative eGFR slope, then name."""
    flagged = [r for r in rows if r.attention is not None]
    flagged.sort(key=lambda r: (r.attention.rank, _slope(r), r.name.casefold(), str(r.facts.patient_id)))  # type: ignore[union-attr]
    return [AttentionRow(r.facts.patient_id, r.mrn, r.name, r.age, r.attention.rank, r.attention.reasons)  # type: ignore[union-attr]
            for r in flagged]


def egfr_distribution(rows: Sequence[PatientRow]) -> dict[str, int]:
    dist = {g: 0 for g in EGFR_GROUPS} | {"none": 0}
    for r in rows:
        cat = r.facts.labs.egfr_category if r.facts.labs else None
        dist[cat if cat in EGFR_GROUPS else "none"] += 1
    return dist


def abnormal_results(rows: Sequence[PatientRow], *, per_patient: int, total: int) -> list[AbnormalResult]:
    """Per patient: latest abnormal results (critical first, at most ``per_patient``). Then all of them, critical
    first, then newest, first ``total``. ``unknown`` is not abnormal."""
    pool: list[AbnormalResult] = []
    for r in rows:
        if r.facts.labs is None:
            continue
        mine = [lab for lab in r.facts.labs.latest.values() if lab.flag in ABNORMAL_FLAGS]
        mine.sort(key=lambda lab: (not lab.flag.startswith("critical"), -lab.collected_at.timestamp(), lab.test_code))
        for lab in mine[:per_patient]:
            pool.append(AbnormalResult(r.facts.patient_id, r.name, r.mrn, lab.test_code,
                                       TEST_NAMES.get(lab.test_code, lab.test_code), float(lab.value),
                                       fmt_value(lab), lab.unit, lab.flag, lab.collected_at, lab.result_id))
    pool.sort(key=lambda a: (not a.flag.startswith("critical"), -a.collected_at.timestamp(), a.name.casefold(), a.test))
    return pool[:total]


def build_dashboard(rows: Sequence[PatientRow], *, attention_limit: int, per_patient: int, total: int) -> Dashboard:
    att = attention_rows(rows)
    kpis = {
        "patients": len(rows),
        "need_attention": len(att),
        "critical_results": sum(1 for r in rows if r.facts.labs and r.facts.labs.has_critical),
        "rapid_decline": sum(1 for r in rows if r.facts.labs and r.facts.labs.rapid_decline),
    }
    return Dashboard(kpis, tuple(att[:attention_limit]), egfr_distribution(rows),
                     tuple(abnormal_results(rows, per_patient=per_patient, total=total)))
