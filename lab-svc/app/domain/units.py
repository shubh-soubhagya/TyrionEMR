"""Unit conversion to the canonical unit (HLD §5.4). Pure: no I/O."""
from __future__ import annotations

from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal


class UnknownUnit(ValueError):
    """The unit is not in the test's allowed_units."""


def to_canonical(value: Decimal, unit: str, allowed_units: Mapping[str, Decimal | str], decimals: int) -> Decimal:
    """Converts ``value`` in ``unit`` to the canonical unit.

    Rounded half-up to ``decimals + 1`` places, the same rule as the browser preview (toCanon in the UI
    prototype), so a value never changes between preview and save.
    """
    if unit not in allowed_units:
        raise UnknownUnit(unit)
    factor = Decimal(allowed_units[unit])
    return (value * factor).quantize(Decimal(1).scaleb(-(decimals + 1)), rounding=ROUND_HALF_UP)
