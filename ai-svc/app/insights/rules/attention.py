"""The attention rule and its reasons (LLD B4.5). PURE."""
from __future__ import annotations

from collections.abc import Sequence

from app.insights.rules.constants import TEST_DECIMALS, TEST_ORDER, display_name
from app.insights.rules.facts import Attention, Finding, LatestLab, PatientFacts, Reason


def fmt_value(lab: LatestLab) -> str:
    return f"{lab.value:.{TEST_DECIMALS.get(lab.test_code, 1)}f}"


def attention(f: PatientFacts, findings: Sequence[Finding]) -> Attention | None:
    """A patient needs attention when the latest result of any test is critical, eGFR shows rapid decline, or any
    finding has severity high (HLD 10.5)."""
    reasons: list[Reason] = []
    if f.labs:
        for lab in sorted(f.labs.latest.values(), key=lambda r: TEST_ORDER.get(r.test_code, 99)):
            if lab.flag.startswith("critical"):
                reasons.append(Reason("danger", "critical_result",
                                      f"Critical {display_name(lab.test_code)} {fmt_value(lab)} {lab.unit}"))
        if f.labs.rapid_decline and f.labs.egfr and f.labs.egfr.slope_per_year is not None:
            reasons.append(Reason("danger", "rapid_decline",
                                  f"eGFR falling {abs(f.labs.egfr.slope_per_year):.1f} per year"))
    for g in [g for g in findings if g.severity == "high"][:2]:
        reasons.append(Reason("warn", g.code, g.message.rstrip(".")))
    if not reasons:
        return None
    rank = 0 if f.labs and f.labs.has_critical else 1 if f.labs and f.labs.rapid_decline else 2
    return Attention(rank=rank, reasons=tuple(reasons))
