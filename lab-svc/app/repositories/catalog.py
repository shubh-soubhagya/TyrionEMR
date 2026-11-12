from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.flagging import RangeDef
from app.domain.units import TestDef
from app.models import LabReferenceRange, LabTest


class CatalogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def tests(self) -> list[TestDef]:
        rows = (await self._s.scalars(select(LabTest).order_by(LabTest.display_order))).all()
        return [TestDef.build(code=t.code, name=t.name, canonical_unit=t.canonical_unit, units=t.allowed_units,
                              decimals=t.decimals, plausible_max=t.plausible_max, display_order=t.display_order)
                for t in rows]

    async def ranges(self) -> list[RangeDef]:
        rows = (await self._s.scalars(select(LabReferenceRange))).all()
        return [RangeDef(r.test_code, r.sex, r.age_min, r.age_max, r.low, r.high, r.critical_low,
                         r.critical_high, r.effective_from, r.id) for r in rows]
