from __future__ import annotations

from decimal import Decimal

from app.domain.clock import Clock
from app.domain.flagging import RangeDef, select_range
from app.repositories.catalog import CatalogRepository
from app.schemas.catalog import AllowedUnit, CatalogOut, LabTestOut, ReferenceRangeOut


def _f(v: Decimal | None) -> float | None:
    return None if v is None else float(v)


def _fmt(v: Decimal) -> str:
    return format(v.normalize(), "f")


def range_text(r: RangeDef) -> str:
    """Same wording as the UI prototype (refText): "0.7–1.3", "≥ 90", "< 30"."""
    if r.low is not None and r.high is not None:
        return f"{_fmt(r.low)}–{_fmt(r.high)}"
    if r.low is not None:
        return f"≥ {_fmt(r.low)}"
    if r.high is not None:
        return f"< {_fmt(r.high)}"
    return "-"


class CatalogService:
    def __init__(self, repo: CatalogRepository, clock: Clock) -> None:
        self._repo = repo
        self._clock = clock

    async def get(self, sex: str | None) -> CatalogOut:
        """The catalog with the range that applies for ``sex``. Age bands are not applied here (no age is
        known), so only age-independent ranges are returned."""
        tests, ranges = await self._repo.tests(), await self._repo.ranges()
        today = self._clock().date()
        out: list[LabTestOut] = []
        for t in tests:
            r = select_range(ranges, t.code, sex, None, today)
            out.append(LabTestOut(
                code=t.code, name=t.name, canonical_unit=t.canonical_unit,
                allowed_units=[AllowedUnit(unit=u, factor=float(f)) for u, f in t.units.items()],
                decimals=t.decimals, max_value=float(t.plausible_max),
                reference_range=None if r is None else ReferenceRangeOut(
                    low=_f(r.low), high=_f(r.high), critical_low=_f(r.critical_low),
                    critical_high=_f(r.critical_high), text=range_text(r)),
            ))
        return CatalogOut(sex=sex, tests=out)
