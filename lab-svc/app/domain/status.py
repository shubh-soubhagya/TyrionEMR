"""Builds the patient_lab_status read model from a patient's current results (LLD B4.6, ADR-015).

Pure: the same function serves the in-transaction recompute and the rebuild script, so they cannot disagree.
``has_critical`` looks at the LATEST result per test only.
"""
from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Final

from app.domain.ckd import classify_egfr, classify_uacr
from app.domain.constants import RULES_VERSION
from app.domain.trends import Point, TrendConfig, trend_stats

DEFAULT_SPARK_POINTS: Final = 12


@dataclass(frozen=True, slots=True)
class ResultPoint:
    id: uuid.UUID
    report_id: uuid.UUID
    test_code: str
    value: Decimal
    unit: str
    flag: str
    collected_at: datetime
    created_at: datetime
    ref_low: Decimal | None = None
    ref_high: Decimal | None = None


def _num(v: Decimal | None) -> float | None:
    return None if v is None else float(v)


def build_status(rows: Sequence[ResultPoint], cfg: TrendConfig = TrendConfig(),  # noqa: B008
                 spark_points: int = DEFAULT_SPARK_POINTS) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda r: (r.collected_at, r.created_at, str(r.id)))
    latest: dict[str, ResultPoint] = {}
    for r in ordered:
        latest[r.test_code] = r                          # the last one wins
    egfr = [r for r in ordered if r.test_code == "EGFR"]
    creat = [r for r in ordered if r.test_code == "CREAT"]
    egfr_stats = trend_stats("EGFR", [Point(r.collected_at, r.value) for r in egfr], cfg)
    creat_stats = trend_stats("CREAT", [Point(r.collected_at, r.value) for r in creat], cfg)
    return {
        "latest": {c: {"result_id": str(r.id), "report_id": str(r.report_id), "value": float(r.value),
                       "unit": r.unit, "flag": r.flag, "collected_at": r.collected_at.isoformat(),
                       "ref_low": _num(r.ref_low), "ref_high": _num(r.ref_high)} for c, r in latest.items()},
        "egfr_category": classify_egfr(latest["EGFR"].value) if "EGFR" in latest else None,
        "uacr_category": classify_uacr(latest["UACR"].value) if "UACR" in latest else None,
        "egfr_stats": egfr_stats.as_dict() if egfr else None,
        "creat_stats": creat_stats.as_dict() if creat else None,
        "egfr_spark": [{"t": r.collected_at.isoformat(), "v": float(r.value)} for r in egfr[-spark_points:]],
        "has_critical": any(r.flag.startswith("critical") for r in latest.values()),
        "rapid_decline": egfr_stats.rapid_decline,
        "result_count": len(ordered),
        "last_result_at": ordered[-1].collected_at if ordered else None,
        "rules_version": RULES_VERSION,
    }
