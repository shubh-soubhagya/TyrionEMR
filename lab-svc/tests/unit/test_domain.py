"""Pure clinical logic (HLD §6): units, flagging, CKD categories, trends."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import pytest

from app.domain.catalog_data import CATALOG, RANGES, RANGES_EFFECTIVE_FROM
from app.domain.ckd import egfr_category, uacr_category
from app.domain.flagging import RangeRow, flag_for, select_range
from app.domain.trends import compute_stats
from app.domain.units import UnknownUnit, to_canonical

ON = date(2026, 11, 11)
SEED_RANGES = [RangeRow(r.test_code, r.sex, None, None, r.low, r.high, r.critical_low, r.critical_high,
                        RANGES_EFFECTIVE_FROM) for r in RANGES]
CAT = {t["code"]: t for t in CATALOG}


# ---- units --------------------------------------------------------------------------------------
def test_creatinine_umol_to_mgdl() -> None:
    t = CAT["CREAT"]
    # 176.8 umol/L * 0.0113 = 1.99784 -> 2 d.p.+1 = 1.998
    assert to_canonical(D("176.8"), "µmol/L", t["allowed_units"], t["decimals"]) == D("1.998")


def test_canonical_unit_is_identity() -> None:
    t = CAT["K"]
    assert to_canonical(D("4.5"), "mEq/L", t["allowed_units"], t["decimals"]) == D("4.50")


def test_rounding_is_half_up() -> None:
    assert to_canonical(D("0.25"), "x", {"x": "1"}, 0) == D("0.3")      # not banker's rounding
    assert to_canonical(D("0.35"), "x", {"x": "1"}, 0) == D("0.4")


def test_unknown_unit_rejected() -> None:
    t = CAT["EGFR"]
    with pytest.raises(UnknownUnit):
        to_canonical(D("50"), "mg/dL", t["allowed_units"], t["decimals"])


def test_every_test_has_its_canonical_unit_with_factor_one() -> None:
    for t in CATALOG:
        assert D(t["allowed_units"][t["canonical_unit"]]) == 1


# ---- range selection ----------------------------------------------------------------------------
def test_range_is_sex_specific_when_available() -> None:
    assert select_range(SEED_RANGES, "CREAT", "F", None, ON).high == D("1.1")       # type: ignore[union-attr]
    assert select_range(SEED_RANGES, "CREAT", "M", None, ON).high == D("1.3")       # type: ignore[union-attr]


def test_sex_independent_range_applies_to_everyone() -> None:
    assert select_range(SEED_RANGES, "K", "F", None, ON) is not None
    assert select_range(SEED_RANGES, "K", None, None, ON) is not None


def test_sex_specific_test_without_sex_has_no_range() -> None:
    assert select_range(SEED_RANGES, "CREAT", None, None, ON) is None


def test_age_band_beats_open_range_and_latest_effective_wins() -> None:
    def row(age_min, age_max, low, eff):
        return RangeRow("K", None, age_min, age_max, D(low), D("5"), None, None, eff)

    rs = [row(None, None, "3.5", date(2020, 1, 1)), row(0, 17, "3.4", date(2020, 1, 1)),
          row(None, None, "3.6", date(2025, 1, 1)), row(None, None, "3.7", date(2030, 1, 1))]
    assert select_range(rs, "K", "M", 10, ON).low == D("3.4")       # type: ignore[union-attr]
    assert select_range(rs, "K", "M", 40, ON).low == D("3.6")       # type: ignore[union-attr]  (2030 not yet)
    assert select_range(rs, "K", "M", None, ON).low == D("3.6")     # type: ignore[union-attr]  banded needs an age


def test_unknown_test_has_no_range() -> None:
    assert select_range(SEED_RANGES, "NOPE", "M", 50, ON) is None


# ---- flagging -----------------------------------------------------------------------------------
@pytest.mark.parametrize(("code", "sex", "value", "expected"), [
    ("K", "M", "3.5", "normal"), ("K", "M", "5.0", "normal"),          # limits are inclusive of normal
    ("K", "M", "3.4", "low"), ("K", "M", "5.1", "high"),
    ("K", "M", "2.8", "low"), ("K", "M", "2.7", "critical_low"),
    ("K", "M", "6.0", "high"), ("K", "M", "6.1", "critical_high"),
    ("CREAT", "M", "1.3", "normal"), ("CREAT", "M", "1.4", "high"), ("CREAT", "M", "5.1", "critical_high"),
    ("CREAT", "F", "1.2", "high"),                                      # normal for M, high for F
    ("EGFR", "M", "90", "normal"), ("EGFR", "M", "89", "low"), ("EGFR", "M", "10", "low"),
    ("EGFR", "M", "9", "critical_low"),
    ("UACR", "M", "30", "normal"), ("UACR", "M", "31", "high"),
    ("HB", "F", "6.9", "critical_low"), ("HB", "M", "13.4", "low"),
])
def test_flag_boundaries(code: str, sex: str, value: str, expected: str) -> None:
    assert flag_for(D(value), select_range(SEED_RANGES, code, sex, None, ON)) == expected


def test_no_range_is_unknown_never_normal() -> None:
    assert flag_for(D("1"), None) == "unknown"


# ---- CKD ----------------------------------------------------------------------------------------
@pytest.mark.parametrize(("v", "cat"), [
    ("120", "G1"), ("90", "G1"), ("89.9", "G2"), ("60", "G2"), ("59.9", "G3a"), ("45", "G3a"),
    ("44.9", "G3b"), ("30", "G3b"), ("29.9", "G4"), ("15", "G4"), ("14.9", "G5"), ("0", "G5"),
])
def test_egfr_category_boundaries(v: str, cat: str) -> None:
    assert egfr_category(D(v)) == cat


@pytest.mark.parametrize(("v", "cat"), [
    ("0", "A1"), ("29.9", "A1"), ("30", "A2"), ("300", "A2"), ("300.1", "A3"),
])
def test_uacr_category_boundaries(v: str, cat: str) -> None:
    assert uacr_category(D(v)) == cat


# ---- trends -------------------------------------------------------------------------------------
T0 = datetime(2025, 1, 1, tzinfo=UTC)


def series(values: list[float], step_days: int = 90):
    return [(T0 + timedelta(days=i * step_days), D(str(v))) for i, v in enumerate(values)]


def test_empty_series_has_no_stats() -> None:
    assert compute_stats("EGFR", []) is None


def test_two_points_never_extrapolate() -> None:
    s = compute_stats("EGFR", series([62, 40]))
    assert s is not None
    assert s["direction"] == "insufficient_data" and s["slope_per_year"] is None
    assert s["rapid_decline"] is False and s["n"] == 2


def test_linear_decline_slope_and_rapid_flag() -> None:
    # -2 per 30 days -> about -24.35 per year
    s = compute_stats("EGFR", series([60, 58, 56, 54, 52], step_days=30))
    assert s is not None
    assert s["slope_per_year"] == pytest.approx(-24.35, abs=0.01)
    assert s["direction"] == "worsening" and s["rapid_decline"] is True
    assert (s["first"], s["last"], s["abs_change"], s["pct_change"], s["span_days"]) == (60, 52, -8, -13.3, 120)


def test_slow_decline_is_not_rapid() -> None:
    s = compute_stats("EGFR", series([60, 59, 58, 57], step_days=90))        # about -4.06 per year
    assert s is not None and s["direction"] == "worsening" and s["rapid_decline"] is False


def test_stable_and_improving_egfr() -> None:
    assert compute_stats("EGFR", series([50, 50.1, 49.9, 50]))["direction"] == "stable"       # type: ignore[index]
    assert compute_stats("EGFR", series([40, 45, 50, 55]))["direction"] == "improving"        # type: ignore[index]


def test_creatinine_direction_is_inverted() -> None:
    assert compute_stats("CREAT", series([1.0, 1.4, 1.8, 2.2]))["direction"] == "worsening"    # type: ignore[index]
    assert compute_stats("CREAT", series([2.2, 1.8, 1.4, 1.0]))["direction"] == "improving"    # type: ignore[index]
    assert compute_stats("CREAT", series([1.0, 1.0, 1.0]))["direction"] == "stable"            # type: ignore[index]


def test_creatinine_never_rapid_decline() -> None:
    assert compute_stats("CREAT", series([3, 2, 1]))["rapid_decline"] is False                 # type: ignore[index]


def test_points_are_sorted_by_time() -> None:
    pts = list(reversed(series([60, 58, 56, 54], step_days=30)))
    s = compute_stats("EGFR", pts)
    assert s is not None and s["first"] == 60 and s["last"] == 54


def test_same_instant_points_have_no_slope() -> None:
    s = compute_stats("EGFR", [(T0, D(50)), (T0, D(51)), (T0, D(52))])
    assert s is not None and s["slope_per_year"] is None and s["direction"] == "insufficient_data"


def test_zero_first_value_has_no_pct_change() -> None:
    s = compute_stats("UACR", series([0, 5, 10]))
    assert s is not None and s["pct_change"] is None


def test_domain_modules_do_no_io() -> None:
    import ast
    import pathlib
    banned = {"sqlalchemy", "httpx", "fastapi", "asyncio", "requests"}
    for f in pathlib.Path("app/domain").glob("*.py"):
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            mods = ([a.name for a in n.names] if isinstance(n, ast.Import)
                    else [n.module or ""] if isinstance(n, ast.ImportFrom) else [])
            assert not {m.split(".")[0] for m in mods} & banned, f
