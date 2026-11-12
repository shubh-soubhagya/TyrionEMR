"""Units and conversion (LLD B4.1). Pure: no I/O.

Unit strings reach us in several Unicode spellings (MICRO SIGN vs GREEK MU, superscript two), so matching uses a
normalised key and the stored ``unit_original`` is always the catalog's own spelling.
"""
from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal


class UnknownUnit(ValueError):
    def __init__(self, test_code: str, unit: str, allowed: list[str]) -> None:
        super().__init__(f"{unit!r} is not an accepted unit for {test_code}")
        self.test_code, self.unit, self.allowed = test_code, unit, allowed


def unit_key(unit: str) -> str:
    """Matching key: 'µmol/L', 'μmol/L', 'umol/L', 'UMOL / L' -> 'umol/l';
    'mL/min/1.73m²' and 'mL/min/1.73m2' -> 'ml/min/1.73m2'."""
    s = unicodedata.normalize("NFKC", unit)        # superscript two -> '2'; MICRO SIGN -> GREEK MU
    s = s.replace("μ", "u")
    return "".join(s.split()).casefold()


@dataclass(frozen=True, slots=True)
class TestDef:
    """One catalog test, immutable. ``units`` maps the display spelling to the exact factor to canonical."""

    __test__ = False                                # not a pytest class, despite the name

    code: str
    name: str
    canonical_unit: str
    units: Mapping[str, Decimal]
    decimals: int
    plausible_max: Decimal
    display_order: int
    unit_index: Mapping[str, str] = field(default_factory=dict)       # unit_key -> display spelling

    @classmethod
    def build(cls, *, code: str, name: str, canonical_unit: str, units: Mapping[str, Decimal | str], decimals: int,
              plausible_max: Decimal | str | float, display_order: int) -> TestDef:
        exact = {u: Decimal(f) for u, f in units.items()}
        index: dict[str, str] = {}
        for display in exact:
            key = unit_key(display)
            if key in index:                         # two units of one test must never share a key
                raise ValueError(f"{code}: units {index[key]!r} and {display!r} are ambiguous")
            index[key] = display
        if canonical_unit not in exact or exact[canonical_unit] != 1:
            raise ValueError(f"{code}: the canonical unit must be listed with factor 1")
        return cls(code, name, canonical_unit, exact, decimals, Decimal(str(plausible_max)), display_order, index)


def resolve_unit(test: TestDef, unit: str) -> str:
    """The catalog's spelling of ``unit`` for this test, or UnknownUnit (carrying the allowed units)."""
    display = test.unit_index.get(unit_key(unit))
    if display is None:
        raise UnknownUnit(test.code, unit, allowed=list(test.units))
    return display


def to_canonical(test: TestDef, value: Decimal, unit_display: str) -> Decimal:
    """Exact decimal conversion, rounded half-up to ``decimals + 1`` places (the prototype's rule), so a
    value never changes between the browser preview and the saved result."""
    quantum = Decimal(1).scaleb(-(test.decimals + 1))
    return (value * test.units[unit_display]).quantize(quantum, rounding=ROUND_HALF_UP)
