"""CKD-EPI 2021 creatinine equation, race-free (LLD B4.4). PURE."""
from __future__ import annotations

from datetime import date
from typing import Literal


def ckd_epi_2021(scr_mg_dl: float, age_years: int, sex: Literal["M", "F"]) -> float:
    kappa = 0.7 if sex == "F" else 0.9
    alpha = -0.241 if sex == "F" else -0.302
    ratio = scr_mg_dl / kappa
    egfr = 142 * min(ratio, 1) ** alpha * max(ratio, 1) ** -1.200 * 0.9938 ** age_years
    return egfr * 1.012 if sex == "F" else egfr


def age_on(dob: date, on: date) -> int:
    """Completed years on ``on`` (the collection date, not today)."""
    return on.year - dob.year - ((on.month, on.day) < (dob.month, dob.day))
