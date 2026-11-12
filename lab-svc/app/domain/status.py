"""Builds the patient_lab_status read model from a patient's effective results (HLD 5.4, ADR-015).

Pure: the same function serves the incremental update (inside the write transaction) and the rebuild script,
so the two can never disagree. ``has_critical`` looks at the LATEST result per test only.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Final

from app.domain.ckd import egfr_category, uacr_category
from app.domain.constants import RULES_VERSION
from app.domain.trends import DEFAULT_CONFIG, TrendConfig, compute_stats

SPARK_POINTS: Final = 12


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


def build_status(points: Sequence[ResultPoint], config: TrendConfig = DEFAULT_CONFIG) -> dict[str, Any]:
    by_test: dict[str, list[ResultPoint]] = defaultdict(list)
    for p in points:
        by_test[p.test_code].append(p)
    ordered = {c: sorted(ps, key=lambda p: (p.collected_at, p.created_at)) for c, ps in by_test.items()}
    latest_pts = {c: ps[-1] for c, ps in ordered.items()}
    latest = {c: {"result_id": str(p.id), "report_id": str(p.report_id), "value": float(p.value),
                  "unit": p.unit, "flag": p.flag, "collected_at": p.collected_at.isoformat()}
              for c, p in latest_pts.items()}
    egfr, creat = ordered.get("EGFR", []), ordered.get("CREAT", [])
    stats_egfr = compute_stats("EGFR", [(p.collected_at, p.value) for p in egfr], config)
    stats_creat = compute_stats("CREAT", [(p.collected_at, p.value) for p in creat], config)
    return {
        "latest": latest,
        "egfr_category": egfr_category(latest_pts["EGFR"].value) if "EGFR" in latest_pts else None,
        "uacr_category": uacr_category(latest_pts["UACR"].value) if "UACR" in latest_pts else None,
        "egfr_stats": stats_egfr,
        "creat_stats": stats_creat,
        "egfr_spark": [{"t": p.collected_at.isoformat(), "v": float(p.value)} for p in egfr[-SPARK_POINTS:]],
        "has_critical": any(p.flag.startswith("critical") for p in latest_pts.values()),
        "rapid_decline": bool(stats_egfr and stats_egfr["rapid_decline"]),
        "result_count": len(points),
        "last_result_at": max((p.collected_at for p in points), default=None),
        "rules_version": RULES_VERSION,
    }
