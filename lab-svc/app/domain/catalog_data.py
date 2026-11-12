"""Test catalog and reference ranges seed (HLD §6.2).

Single configurable source for ranges, units and plausibility limits (CLAUDE.md §7). Values are taken from
the reference UI prototype (reference/emr-ui.html, LAB_TESTS) so the browser preview and the server agree.
If the assignment's supplied ranges file differs, only this file changes.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal as D
from typing import Final, NamedTuple, TypedDict


class CatalogTest(TypedDict):
    code: str
    name: str
    canonical_unit: str
    allowed_units: dict[str, str]     # unit -> factor to canonical, strings so Decimal stays exact
    decimals: int
    max_value: str
    sort_order: int


class RangeSeed(NamedTuple):
    test_code: str
    sex: str | None
    low: D | None
    high: D | None
    critical_low: D | None
    critical_high: D | None


RANGES_EFFECTIVE_FROM: Final = date(2020, 1, 1)

CATALOG: Final[tuple[CatalogTest, ...]] = (
    {"code": "CREAT", "name": "Serum creatinine", "canonical_unit": "mg/dL", "decimals": 2, "max_value": "30",
     "allowed_units": {"mg/dL": "1", "µmol/L": "0.0113"}, "sort_order": 1},
    {"code": "EGFR", "name": "eGFR", "canonical_unit": "mL/min/1.73m²", "decimals": 0, "max_value": "200",
     "allowed_units": {"mL/min/1.73m²": "1"}, "sort_order": 2},
    {"code": "BUN", "name": "Blood urea nitrogen", "canonical_unit": "mg/dL", "decimals": 1, "max_value": "300",
     "allowed_units": {"mg/dL": "1", "mmol/L (urea)": "2.8"}, "sort_order": 3},
    {"code": "K", "name": "Potassium", "canonical_unit": "mmol/L", "decimals": 1, "max_value": "12",
     "allowed_units": {"mmol/L": "1", "mEq/L": "1"}, "sort_order": 4},
    {"code": "HB", "name": "Hemoglobin", "canonical_unit": "g/dL", "decimals": 1, "max_value": "25",
     "allowed_units": {"g/dL": "1", "g/L": "0.1"}, "sort_order": 5},
    {"code": "CA", "name": "Calcium", "canonical_unit": "mg/dL", "decimals": 1, "max_value": "20",
     "allowed_units": {"mg/dL": "1", "mmol/L": "4.008"}, "sort_order": 6},
    {"code": "PHOS", "name": "Phosphorus", "canonical_unit": "mg/dL", "decimals": 1, "max_value": "20",
     "allowed_units": {"mg/dL": "1", "mmol/L": "3.097"}, "sort_order": 7},
    {"code": "UACR", "name": "Urine albumin-creatinine ratio", "canonical_unit": "mg/g", "decimals": 0,
     "max_value": "20000", "allowed_units": {"mg/g": "1", "mg/mmol": "8.84"}, "sort_order": 8},
)

RANGES: Final[tuple[RangeSeed, ...]] = (
    RangeSeed("CREAT", "M", D("0.7"), D("1.3"), None, D("5.0")),
    RangeSeed("CREAT", "F", D("0.6"), D("1.1"), None, D("5.0")),
    RangeSeed("EGFR", None, D("90"), None, D("10"), None),
    RangeSeed("BUN", None, D("7"), D("20"), None, D("100")),
    RangeSeed("K", None, D("3.5"), D("5.0"), D("2.8"), D("6.0")),
    RangeSeed("HB", "M", D("13.5"), D("17.5"), D("7.0"), None),
    RangeSeed("HB", "F", D("12.0"), D("15.5"), D("7.0"), None),
    RangeSeed("CA", None, D("8.5"), D("10.5"), D("6.5"), D("13.0")),
    RangeSeed("PHOS", None, D("2.5"), D("4.5"), D("1.0"), D("8.0")),
    RangeSeed("UACR", None, None, D("30"), None, None),
)
