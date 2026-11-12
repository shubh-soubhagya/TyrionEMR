"""Idempotent seed of the test catalog and reference ranges (reference data, safe to run on every start).

Upserts by key: re-running changes nothing. Ranges are keyed by (test, sex, age band, effective_from), so a
revised range is a NEW row with a later ``effective_from`` and old results keep their snapshot (ADR-009).
"""
from __future__ import annotations

import asyncio
import json
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import create_engine, create_sessionmaker
from app.domain.catalog_data import CATALOG, RANGES, RANGES_EFFECTIVE_FROM, RANGES_SOURCE


async def seed_catalog(session: AsyncSession) -> None:
    for t in CATALOG:
        await session.execute(text("""
            INSERT INTO lab_tests (code, name, canonical_unit, allowed_units, decimals, plausible_max, display_order)
            VALUES (:code, :name, :cu, CAST(:au AS jsonb), :dec, :mx, :so)
            ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, canonical_unit = EXCLUDED.canonical_unit,
              allowed_units = EXCLUDED.allowed_units, decimals = EXCLUDED.decimals,
              plausible_max = EXCLUDED.plausible_max, display_order = EXCLUDED.display_order,
              updated_at = now()"""),
            {"code": t["code"], "name": t["name"], "cu": t["canonical_unit"],
             "au": json.dumps(t["allowed_units"], ensure_ascii=False), "dec": t["decimals"],
             "mx": Decimal(t["max_value"]), "so": t["sort_order"]})
    for r in RANGES:
        await session.execute(text("""
            INSERT INTO lab_reference_ranges
              (test_code, sex, low, high, critical_low, critical_high, effective_from, source)
            VALUES (:tc, :sex, :lo, :hi, :cl, :ch, :eff, :src)
            ON CONFLICT (test_code, COALESCE(sex, '*'), COALESCE(age_min, -1), COALESCE(age_max, -1),
                         effective_from)
            DO UPDATE SET low = EXCLUDED.low, high = EXCLUDED.high,
              critical_low = EXCLUDED.critical_low, critical_high = EXCLUDED.critical_high,
              source = EXCLUDED.source"""),
            {"tc": r.test_code, "sex": r.sex, "lo": r.low, "hi": r.high, "cl": r.critical_low,
             "ch": r.critical_high, "eff": RANGES_EFFECTIVE_FROM, "src": RANGES_SOURCE})
    await session.commit()


async def main() -> None:
    engine = create_engine(get_settings())
    try:
        async with create_sessionmaker(engine)() as session:
            await seed_catalog(session)
        print(f"catalog seeded: {len(CATALOG)} tests, {len(RANGES)} ranges")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
