from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.flagging import RangeRow
from app.models import LabReferenceRange, LabTest


class CatalogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def tests(self) -> list[LabTest]:
        return list((await self._s.scalars(select(LabTest).order_by(LabTest.display_order))).all())

    async def ranges(self) -> list[RangeRow]:
        rows = (await self._s.scalars(select(LabReferenceRange))).all()
        return [RangeRow(r.test_code, r.sex, r.age_min, r.age_max, r.low, r.high, r.critical_low,
                         r.critical_high, r.effective_from, r.id) for r in rows]
