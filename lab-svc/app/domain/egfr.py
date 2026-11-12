"""CKD-EPI 2021 (race-free) creatinine equation. Pure: no I/O.

Used by the synthetic seed so creatinine and eGFR agree (HLD 18); never used to compute a stored clinical
value from user input, because eGFR is a reported lab result here, not something the service derives.
"""
from __future__ import annotations

from typing import Final

_PARAMS: Final = {"F": (0.7, -0.241, 1.012), "M": (0.9, -0.302, 1.0)}      # k, alpha, sex factor
_BASE: Final = 142.0
_AGE_BASE: Final = 0.9938


def _params(sex: str) -> tuple[float, float, float]:
    return _PARAMS[sex]            # KeyError for "O": the equation is defined for M and F only


def egfr_ckd_epi_2021(creatinine_mg_dl: float, age: int, sex: str) -> float:
    k, alpha, factor = _params(sex)
    ratio = creatinine_mg_dl / k
    return _BASE * min(ratio, 1.0) ** alpha * max(ratio, 1.0) ** -1.200 * _AGE_BASE**age * factor


def creatinine_for_egfr(egfr: float, age: int, sex: str) -> float:
    """Inverse of ``egfr_ckd_epi_2021`` (mg/dL)."""
    k, alpha, factor = _params(sex)
    base = _BASE * _AGE_BASE**age * factor           # eGFR when the creatinine ratio is exactly 1
    if egfr >= base:                                  # ratio < 1: the alpha branch
        return k * (egfr / base) ** (1.0 / alpha)
    return k * (egfr / base) ** (-1.0 / 1.200)
