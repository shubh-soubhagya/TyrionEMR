"""KDIGO categories (LLD B4.4). Thresholds are lower-inclusive: 60 -> G2, 59.9 -> G3a. Pure: no I/O.

Applied to the CANONICAL stored value (one extra decimal), so 59.95 entered as eGFR is stored as 60.0 and is G2.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Final

# (category, inclusive lower bound, description), descending; G5 has no bound
EGFR_CATEGORIES: Final[tuple[tuple[str, Decimal | None, str], ...]] = (
    ("G1", Decimal(90), "Normal or high"),
    ("G2", Decimal(60), "Mildly decreased"),
    ("G3a", Decimal(45), "Mild to moderately decreased"),
    ("G3b", Decimal(30), "Moderately to severely decreased"),
    ("G4", Decimal(15), "Severely decreased"),
    ("G5", None, "Kidney failure"),
)
EGFR_LABELS: Final = {code: label for code, _, label in EGFR_CATEGORIES}
UACR_LABELS: Final = {"A1": "Normal to mildly increased", "A2": "Moderately increased", "A3": "Severely increased"}

# for the eGFR chart: the client draws the bands from this and never hard-codes them
STAGE_BANDS: Final = [{"code": code, "lower": int(lower or 0)} for code, lower, _ in EGFR_CATEGORIES]

UACR_A2_FROM: Final = Decimal(30)
UACR_A3_ABOVE: Final = Decimal(300)          # mg/g: A1 < 30, A2 30-300 inclusive, A3 > 300


def classify_egfr(egfr: Decimal) -> str:
    for code, lower, _ in EGFR_CATEGORIES:
        if lower is None or egfr >= lower:
            return code
    raise AssertionError("unreachable: G5 has no lower bound")


def classify_uacr(uacr: Decimal) -> str:
    if uacr > UACR_A3_ABOVE:
        return "A3"
    if uacr >= UACR_A2_FROM:
        return "A2"
    return "A1"
