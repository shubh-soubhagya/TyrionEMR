"""Pure clinical logic (LLD B4, test plan B13.1) and the shared vectors (B13.3)."""
from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path

import pytest

from app.domain.catalog_data import CATALOG, RANGES, RANGES_EFFECTIVE_FROM
from app.domain.ckd import STAGE_BANDS, classify_egfr, classify_uacr
from app.domain.constants import RULES_VERSION
from app.domain.flagging import RangeDef, age_on, flag_for, select_range
from app.domain.status import ResultPoint, build_status
from app.domain.trends import Point, TrendConfig, trend_stats
from app.domain.units import TestDef, UnknownUnit, resolve_unit, to_canonical, unit_key

ON = date(2026, 11, 11)
SEED_RANGES = [RangeDef(r.test_code, r.sex, None, None, r.low, r.high, r.critical_low, r.critical_high,
                        RANGES_EFFECTIVE_FROM) for r in RANGES]
TESTS = {t["code"]: TestDef.build(code=t["code"], name=t["name"], canonical_unit=t["canonical_unit"],
                                  units=t["allowed_units"], decimals=t["decimals"],
                                  plausible_max=t["plausible_max"], display_order=t["display_order"])
         for t in CATALOG}


def canon(code: str, value: str, unit: str) -> D:
    t = TESTS[code]
    return to_canonical(t, D(value), resolve_unit(t, unit))


# ---- units (B4.1) -------------------------------------------------------------------------------
@pytest.mark.parametrize("spelling", ["µmol/L", "μmol/L", "umol/L", "UMOL / L", "umol/l", " µmol /L "])
def test_micromolar_spellings_resolve_to_the_catalog_spelling(spelling: str) -> None:
    assert resolve_unit(TESTS["CREAT"], spelling) == "µmol/L"           # MICRO SIGN, as stored in the catalog


@pytest.mark.parametrize("spelling", ["mL/min/1.73m²", "mL/min/1.73m2", "ML/MIN/1.73M2"])
def test_egfr_unit_spellings(spelling: str) -> None:
    assert resolve_unit(TESTS["EGFR"], spelling) == "mL/min/1.73m²"


def test_bare_mmol_is_not_accepted_for_bun_and_error_lists_allowed_units() -> None:
    with pytest.raises(UnknownUnit) as e:
        resolve_unit(TESTS["BUN"], "mmol/L")
    assert e.value.allowed == ["mg/dL", "mmol/L (urea)"]


def test_unit_key_normalises_unicode() -> None:
    assert unit_key("µmol/L") == unit_key("μmol/L") == unit_key("umol/L") == "umol/l"


def test_ambiguous_units_are_rejected_when_the_catalog_loads() -> None:
    with pytest.raises(ValueError, match="ambiguous"):
        TestDef.build(code="X", name="x", canonical_unit="mg/dL", units={"mg/dL": "1", "MG / dl": "2"},
                      decimals=1, plausible_max=10, display_order=1)


def test_canonical_unit_must_have_factor_one() -> None:
    with pytest.raises(ValueError, match="factor 1"):
        TestDef.build(code="X", name="x", canonical_unit="mg/dL", units={"mg/dL": "2"}, decimals=1,
                      plausible_max=10, display_order=1)


def test_every_factor_in_the_catalog_converts_exactly() -> None:
    assert canon("CREAT", "176.8", "µmol/L") == D("1.998")
    assert canon("BUN", "10", "mmol/L (urea)") == D("28.00")
    assert canon("HB", "115", "g/L") == D("11.50")
    assert canon("CA", "2.2", "mmol/L") == D("8.82")
    assert canon("PHOS", "1.5", "mmol/L") == D("4.65")
    assert canon("UACR", "30", "mg/mmol") == D("265.2")
    assert canon("K", "4.5", "mEq/L") == D("4.50")


def test_rounding_is_half_up_at_decimals_plus_one() -> None:
    t = TestDef.build(code="X", name="x", canonical_unit="u", units={"u": "1"}, decimals=0, plausible_max=9,
                      display_order=1)
    assert to_canonical(t, D("0.25"), "u") == D("0.3")           # not banker's rounding
    assert to_canonical(t, D("0.35"), "u") == D("0.4")


def test_float_trap_case_is_exact() -> None:
    assert canon("CREAT", "150", "µmol/L") == D("1.695")          # 150 * 0.0113 is 1.6949999999999998 as a float


# ---- range selection (B4.2) ----------------------------------------------------------------------
def test_range_is_sex_specific_when_available() -> None:
    assert select_range(SEED_RANGES, "CREAT", "F", 50, ON).high == D("1.1")       # type: ignore[union-attr]
    assert select_range(SEED_RANGES, "CREAT", "M", 50, ON).high == D("1.3")       # type: ignore[union-attr]


def test_sex_other_gets_the_any_sex_range_or_none() -> None:
    assert select_range(SEED_RANGES, "K", "O", 50, ON) is not None
    assert select_range(SEED_RANGES, "CREAT", "O", 50, ON) is None
    assert select_range(SEED_RANGES, "HB", "O", 50, ON) is None


def test_age_band_beats_open_range_and_latest_effective_wins() -> None:
    def row(age_min, age_max, low, eff):
        return RangeDef("K", None, age_min, age_max, D(low), D("5"), None, None, eff)

    rs = [row(None, None, "3.5", date(2020, 1, 1)), row(0, 17, "3.4", date(2020, 1, 1)),
          row(None, None, "3.6", date(2025, 1, 1)), row(None, None, "3.7", date(2030, 1, 1))]
    assert select_range(rs, "K", "M", 10, ON).low == D("3.4")       # type: ignore[union-attr]
    assert select_range(rs, "K", "M", 40, ON).low == D("3.6")       # type: ignore[union-attr]  (2030 not yet)
    assert select_range(rs, "K", "M", None, ON).low == D("3.6")     # type: ignore[union-attr]  banded needs an age


def test_report_dated_before_a_revision_uses_the_range_in_force_then() -> None:
    rs = [RangeDef("K", None, None, None, D("3.5"), D("5.0"), None, None, date(2020, 1, 1)),
          RangeDef("K", None, None, None, D("3.8"), D("5.2"), None, None, date(2026, 1, 1))]
    assert select_range(rs, "K", "M", 40, date(2024, 6, 1)).high == D("5.0")      # type: ignore[union-attr]
    assert select_range(rs, "K", "M", 40, date(2026, 6, 1)).high == D("5.2")      # type: ignore[union-attr]


def test_unknown_test_has_no_range() -> None:
    assert select_range(SEED_RANGES, "NOPE", "M", 50, ON) is None


def test_age_on() -> None:
    assert age_on(date(1959, 4, 17), date(2026, 4, 16)) == 66
    assert age_on(date(1959, 4, 17), date(2026, 4, 17)) == 67


# ---- flagging (B4.3) -----------------------------------------------------------------------------
@pytest.mark.parametrize(("code", "sex", "value", "expected"), [
    ("K", "M", "3.5", "normal"), ("K", "M", "5.0", "normal"),          # a value equal to a limit is not beyond it
    ("K", "M", "3.4", "low"), ("K", "M", "5.1", "high"),
    ("K", "M", "2.8", "low"), ("K", "M", "2.7", "critical_low"),
    ("K", "M", "6.0", "high"), ("K", "M", "6.1", "critical_high"),
    ("CREAT", "M", "1.3", "normal"), ("CREAT", "M", "1.4", "high"), ("CREAT", "M", "5.0", "high"),
    ("CREAT", "M", "5.1", "critical_high"), ("CREAT", "F", "1.2", "high"),
    ("EGFR", "M", "90", "normal"), ("EGFR", "M", "89", "low"), ("EGFR", "M", "10", "low"),
    ("EGFR", "M", "9", "critical_low"),
    ("UACR", "M", "30", "normal"), ("UACR", "M", "31", "high"),
    ("HB", "F", "7.0", "low"), ("HB", "F", "6.9", "critical_low"), ("HB", "M", "13.4", "low"),
])
def test_flag_boundaries(code: str, sex: str, value: str, expected: str) -> None:
    assert flag_for(D(value), select_range(SEED_RANGES, code, sex, 50, ON)) == expected


def test_no_range_is_unknown_never_normal() -> None:
    assert flag_for(D("1"), None) == "unknown"


# ---- CKD (B4.4) ----------------------------------------------------------------------------------
@pytest.mark.parametrize(("v", "cat"), [
    ("120", "G1"), ("90", "G1"), ("89.9", "G2"), ("60", "G2"), ("59.9", "G3a"), ("45", "G3a"),
    ("44.9", "G3b"), ("30", "G3b"), ("29.9", "G4"), ("15", "G4"), ("14.9", "G5"), ("0", "G5"),
])
def test_egfr_category_boundaries(v: str, cat: str) -> None:
    assert classify_egfr(D(v)) == cat


@pytest.mark.parametrize(("v", "cat"), [
    ("0", "A1"), ("29.9", "A1"), ("30", "A2"), ("300", "A2"), ("300.1", "A3"),
])
def test_uacr_category_boundaries(v: str, cat: str) -> None:
    assert classify_uacr(D(v)) == cat


def test_stage_bands_for_the_chart() -> None:
    assert STAGE_BANDS == [{"code": "G1", "lower": 90}, {"code": "G2", "lower": 60}, {"code": "G3a", "lower": 45},
                           {"code": "G3b", "lower": 30}, {"code": "G4", "lower": 15}, {"code": "G5", "lower": 0}]


# ---- trends (B4.5) -------------------------------------------------------------------------------
T0 = datetime(2025, 1, 1, tzinfo=UTC)


def series(values: list[float], step_days: int = 90) -> list[Point]:
    return [Point(T0 + timedelta(days=i * step_days), D(str(v))) for i, v in enumerate(values)]


def test_empty_series_is_no_data() -> None:
    assert trend_stats("EGFR", []).as_dict() == {"n": 0, "direction": "no_data"}


@pytest.mark.parametrize("n", [1, 2])
def test_fewer_than_three_points_never_extrapolate(n: int) -> None:
    s = trend_stats("EGFR", series([62, 40][:n]))
    assert s.direction == "insufficient_data" and s.slope_per_year is None and s.rapid_decline is False


def test_identical_timestamps_have_no_slope() -> None:
    s = trend_stats("EGFR", [Point(T0, D(50)), Point(T0, D(51)), Point(T0, D(52))])
    assert s.slope_per_year is None and s.direction == "insufficient_data"


def test_known_slope_from_a_synthetic_line() -> None:
    s = trend_stats("EGFR", series([60, 58, 56, 54, 52], step_days=30))          # -2 per 30 d = -24.35 / year
    assert s.slope_per_year == pytest.approx(-24.35, abs=0.01)
    assert s.direction == "worsening" and s.rapid_decline is True
    assert (s.first, s.last, s.abs_change, s.pct_change, s.span_days) == (D(60), D(52), D(-8), -13.3, 120)
    assert s.first_at == T0 and s.last_at == T0 + timedelta(days=120)


def yearly(values: list[str]) -> list[Point]:
    """Points exactly one (Julian) year apart, so the OLS slope is exact in binary floating point."""
    return [Point(T0 + timedelta(days=365.25 * i), D(v)) for i, v in enumerate(values)]


def test_egfr_direction_bands_are_inclusive() -> None:
    cfg = TrendConfig(egfr_stable_band=1.0, egfr_rapid_decline=-5.0)
    assert trend_stats("EGFR", yearly(["50", "49", "48"]), cfg).direction == "worsening"      # slope -1.0 <= -1.0
    assert trend_stats("EGFR", yearly(["48", "49", "50"]), cfg).direction == "improving"      # slope +1.0 >= +1.0
    assert trend_stats("EGFR", yearly(["50", "49.5", "49"]), cfg).direction == "stable"       # slope -0.5
    flat = trend_stats("EGFR", series([50, 50.1, 49.9, 50]))
    assert flat.direction == "stable"
    assert trend_stats("EGFR", series([40, 45, 50, 55])).direction == "improving"


def test_rapid_decline_boundary_is_inclusive() -> None:
    cfg = TrendConfig(egfr_rapid_decline=-1.0)
    assert trend_stats("EGFR", yearly(["50", "49", "48"]), cfg).rapid_decline is True        # slope -1.0 <= -1.0
    assert trend_stats("EGFR", yearly(["50", "49.5", "49"]), cfg).rapid_decline is False
    slower = trend_stats("EGFR", series([60, 59, 58, 57], step_days=90))                     # about -4 per year
    assert slower.direction == "worsening" and slower.rapid_decline is False


def test_creatinine_direction_is_inverted_and_strict() -> None:
    assert trend_stats("CREAT", series([1.0, 1.4, 1.8, 2.2])).direction == "worsening"
    assert trend_stats("CREAT", series([2.2, 1.8, 1.4, 1.0])).direction == "improving"
    assert trend_stats("CREAT", series([1.0, 1.0, 1.0])).direction == "stable"
    cfg = TrendConfig(creat_stable_band=0.5)
    assert trend_stats("CREAT", yearly(["1.0", "1.5", "2.0"]), cfg).direction == "stable"      # +0.5 is not beyond 0.5
    assert trend_stats("CREAT", yearly(["1.0", "1.6", "2.2"]), cfg).direction == "worsening"


def test_other_tests_are_not_assessed_but_still_get_a_slope() -> None:
    s = trend_stats("K", series([4.0, 4.2, 4.4, 4.6]))
    assert s.direction == "not_assessed" and s.slope_per_year is not None and s.rapid_decline is False


def test_creatinine_never_rapid_decline() -> None:
    assert trend_stats("CREAT", series([3, 2, 1])).rapid_decline is False


def test_points_are_ordered_by_time() -> None:
    s = trend_stats("EGFR", list(reversed(series([60, 58, 56, 54], step_days=30))))
    assert s.first == D(60) and s.last == D(54)


def test_pct_change_with_zero_first_value_is_none() -> None:
    assert trend_stats("UACR", series([0, 5, 10])).pct_change is None


# ---- read-model builder (B4.6) -------------------------------------------------------------------
def rp(code: str, value: str, days: int, flag: str = "normal", created: int = 0) -> ResultPoint:
    return ResultPoint(uuid.uuid4(), uuid.uuid4(), code, D(value), "u", flag, T0 + timedelta(days=days),
                       T0 + timedelta(days=created or days))


def test_latest_wins_by_time_and_a_back_dated_result_does_not_replace_it() -> None:
    newest = rp("K", "4.0", 100)
    snap = build_status([rp("K", "5.0", 10), newest, rp("K", "4.8", 50, created=200)])        # back-dated, entered last
    assert snap["latest"]["K"]["result_id"] == str(newest.id)


def test_critical_comes_only_from_the_latest_result_per_test() -> None:
    assert build_status([rp("K", "6.8", 1, "critical_high"), rp("K", "4.0", 9)])["has_critical"] is False
    assert build_status([rp("K", "4.0", 1), rp("K", "6.8", 9, "critical_high")])["has_critical"] is True


def test_spark_keeps_the_last_points_in_time_order() -> None:
    rows = [rp("EGFR", str(70 - i), i * 7) for i in range(15)]
    spark = build_status(rows, spark_points=12)["egfr_spark"]
    assert [p["v"] for p in spark] == [67 - i for i in range(12)] and spark[0]["t"] < spark[-1]["t"]


def test_categories_counts_and_rules_version() -> None:
    snap = build_status([rp("EGFR", "44", 5), rp("UACR", "450", 5)])
    assert (snap["egfr_category"], snap["uacr_category"], snap["result_count"]) == ("G3b", "A3", 2)
    assert snap["rules_version"] == RULES_VERSION
    empty = build_status([])
    assert empty["latest"] == {} and empty["egfr_stats"] is None and empty["last_result_at"] is None


# ---- shared vectors (B13.3) ----------------------------------------------------------------------
VECTORS = json.loads((Path(__file__).resolve().parents[1] / "vectors" / "lab_cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", VECTORS, ids=[c["id"] for c in VECTORS])
def test_shared_vector(case: dict) -> None:
    test = TESTS[case["test"]]
    value = to_canonical(test, D(case["value"]), resolve_unit(test, case["unit"]))
    exp = case["expect"]
    assert str(value) == exp["canonical"]
    assert flag_for(value, select_range(SEED_RANGES, test.code, case["sex"], case["age"], ON)) == exp["flag"]
    if "category" in exp:
        assert classify_egfr(value) == exp["category"]
    if "uacr_category" in exp:
        assert classify_uacr(value) == exp["uacr_category"]


def test_domain_modules_do_no_io() -> None:
    import ast
    banned = {"sqlalchemy", "httpx", "fastapi", "asyncio", "requests"}
    for f in Path("app/domain").glob("*.py"):
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            mods = ([a.name for a in n.names] if isinstance(n, ast.Import)
                    else [n.module or ""] if isinstance(n, ast.ImportFrom) else [])
            assert not {m.split(".")[0] for m in mods} & banned, f
