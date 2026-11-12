"""Constants shared by the rules (LLD B4.5, B4.7). PURE: no I/O.

Test names and display decimals equal lab-svc's catalog; a contract test (phase 10) asserts it so the reason text
never drifts from the lab form.
"""
from __future__ import annotations

from typing import Final

# Bump when any rule, message, severity or threshold changes. Part of the summary cache key (AI-ADR-3).
RULES_VERSION: Final = "ai-rules-1"

TEST_ORDER: Final[dict[str, int]] = {c: i for i, c in enumerate(
    ("CREAT", "EGFR", "BUN", "K", "HB", "CA", "PHOS", "UACR"))}
TEST_NAMES: Final[dict[str, str]] = {
    "CREAT": "Serum creatinine", "EGFR": "eGFR", "BUN": "Blood urea nitrogen", "K": "Potassium",
    "HB": "Hemoglobin", "CA": "Calcium", "PHOS": "Phosphorus", "UACR": "Urine albumin-creatinine ratio",
}
TEST_DECIMALS: Final[dict[str, int]] = {
    "CREAT": 2, "EGFR": 0, "BUN": 1, "K": 1, "HB": 1, "CA": 1, "PHOS": 1, "UACR": 0,
}

# Tests whose absence is reported one by one (rule 6), in this order.
REQUIRED_TESTS: Final[tuple[str, ...]] = ("CREAT", "EGFR", "UACR")

ABNORMAL_FLAGS: Final = frozenset({"low", "high", "critical_low", "critical_high"})
EGFR_GROUPS: Final = ("G1", "G2", "G3a", "G3b", "G4", "G5")

TREND_MIN_POINTS: Final = 3            # a trend needs at least this many results (rule 7, 14)
FUTURE_SKEW_S: Final = 60              # rule 12: a result may be at most this far in the future

# Plausible vital-sign ranges: the same limits patient-svc enforces on write (rule 16, defensive).
VITAL_RANGES: Final[dict[str, tuple[float, float]]] = {
    "systolic_bp": (50, 300), "diastolic_bp": (20, 200), "heart_rate": (20, 300),
    "temperature_c": (30, 45), "weight_kg": (1, 500),
}

SEVERITY_ORDER: Final = {"high": 0, "medium": 1, "low": 2}


def display_name(code: str) -> str:
    """Lower-cases only the first letter, so 'eGFR' stays 'eGFR' and 'Serum creatinine' becomes 'serum creatinine'."""
    name = TEST_NAMES.get(code, code)
    return name if name[:2].isupper() or name[:1].islower() else name[0].lower() + name[1:]
