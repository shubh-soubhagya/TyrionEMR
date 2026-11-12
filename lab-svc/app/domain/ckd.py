"""KDIGO categories (HLD §6.1). Thresholds are lower-inclusive: 60 -> G2, 59.9 -> G3a. Pure: no I/O."""
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

# UACR mg/g: A1 < 30, A2 30-300 inclusive, A3 > 300
UACR_A2_FROM: Final = Decimal(30)
UACR_A3_ABOVE: Final = Decimal(300)


def egfr_category(egfr: Decimal) -> str:
    for code, lower, _ in EGFR_CATEGORIES:
        if lower is None or egfr >= lower:
            return code
    raise AssertionError("unreachable: G5 has no lower bound")


def uacr_category(uacr: Decimal) -> str:
    if uacr > UACR_A3_ABOVE:
        return "A3"
    if uacr >= UACR_A2_FROM:
        return "A2"
    return "A1"
