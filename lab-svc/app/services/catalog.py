"""Catalog cache and the catalog view (LLD B6.9, B7.1).

Tests and ranges change only through a migration or the seed, so they are loaded once into immutable objects and
reloaded after ``CATALOG_CACHE_TTL_S``. A short staleness window is harmless; a reload that fails keeps serving
the previous copy instead of taking every write down with it.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import DbUnavailable
from app.core.metrics import CATALOG_RELOADS
from app.domain.clock import Clock
from app.domain.constants import RULES_VERSION
from app.domain.flagging import RangeDef, select_range
from app.domain.units import TestDef
from app.repositories.catalog import CatalogRepository
from app.schemas.catalog import CatalogItem, CatalogOut, RangeOut, UnitOut

log = logging.getLogger("lab.catalog")


@dataclass(frozen=True, slots=True)
class Catalog:
    tests: tuple[TestDef, ...]                 # in display order
    ranges: tuple[RangeDef, ...]
    by_code: Mapping[str, TestDef]


class CatalogCache:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], ttl_s: float,
                 mono: Callable[[], float] = time.monotonic) -> None:
        self._sm, self._ttl, self._mono = sessionmaker, ttl_s, mono
        self._catalog: Catalog | None = None
        self._loaded_at = 0.0
        self._lock = asyncio.Lock()

    @property
    def loaded(self) -> bool:
        return self._catalog is not None

    def invalidate(self) -> None:
        """Expire the copy now (used after a seed or a range revision, and by tests)."""
        self._loaded_at = float("-inf")

    async def load(self) -> Catalog:
        async with self._sm() as session, session.begin():
            repo = CatalogRepository(session)
            tests, ranges = await repo.tests(), await repo.ranges()
        self._catalog = Catalog(tuple(tests), tuple(ranges), {t.code: t for t in tests})
        self._loaded_at = self._mono()
        CATALOG_RELOADS.labels("ok").inc()
        return self._catalog

    async def get(self) -> Catalog:
        if self._catalog is not None and self._mono() - self._loaded_at < self._ttl:
            return self._catalog
        async with self._lock:
            if self._catalog is not None and self._mono() - self._loaded_at < self._ttl:
                return self._catalog                         # another request reloaded it while we waited
            try:
                return await self.load()
            except Exception as exc:
                CATALOG_RELOADS.labels("error").inc()
                log.warning("catalog.reload_failed", extra={"error_type": type(exc).__name__})
                if self._catalog is not None:
                    return self._catalog                     # serve the previous copy
                raise DbUnavailable() from exc


def _fmt(v: Decimal) -> str:
    return format(v.normalize(), "f")


def _f(v: Decimal | None) -> float | None:
    return None if v is None else float(v)


def range_text(r: RangeDef) -> str:
    """Same wording as the UI prototype (refText): "0.7–1.3", "≥ 90", "< 30"."""
    if r.low is not None and r.high is not None:
        return f"{_fmt(r.low)}–{_fmt(r.high)}"
    if r.low is not None:
        return f"≥ {_fmt(r.low)}"
    if r.high is not None:
        return f"< {_fmt(r.high)}"
    return "-"


def range_out(r: RangeDef) -> RangeOut:
    return RangeOut(range_id=r.range_id, sex=r.sex, age_min=r.age_min, age_max=r.age_max, low=_f(r.low),
                    high=_f(r.high), critical_low=_f(r.critical_low), critical_high=_f(r.critical_high),
                    text=range_text(r))


def in_force(ranges: tuple[RangeDef, ...], code: str, today) -> list[RangeDef]:
    """Every range of a test that applies today: the newest per (sex, age band)."""
    newest: dict[tuple, RangeDef] = {}
    for r in ranges:
        if r.test_code == code and r.effective_from <= today:
            key = (r.sex, r.age_min, r.age_max)
            if key not in newest or r.effective_from > newest[key].effective_from:
                newest[key] = r
    return sorted(newest.values(), key=lambda r: (r.sex or "", r.age_min or -1))


class CatalogService:
    def __init__(self, cache: CatalogCache, clock: Clock) -> None:
        self._cache, self._clock = cache, clock

    async def view(self, sex: str | None, age: int | None) -> tuple[CatalogOut, str]:
        """The catalog for the lab form. With ``sex`` each test carries the ONE range that applies today (``null``
        when none does, never a guessed one); without it each test carries all of its ranges in ``ranges``."""
        cat = await self._cache.get()
        today = self._clock().date()
        items: list[CatalogItem] = []
        for t in cat.tests:
            chosen = select_range(cat.ranges, t.code, sex, age, today) if sex else None
            items.append(CatalogItem(
                code=t.code, name=t.name, canonical_unit=t.canonical_unit, decimals=t.decimals,
                plausible_max=float(t.plausible_max), display_order=t.display_order,
                units=[UnitOut(unit=u, factor=format(f, "f")) for u, f in t.units.items()],
                range=None if chosen is None else range_out(chosen),
                ranges=[] if sex else [range_out(r) for r in in_force(cat.ranges, t.code, today)]))
        out = CatalogOut(rules_version=RULES_VERSION, items=items)
        etag = 'W/"cat-' + hashlib.sha256(json.dumps(out.model_dump(mode="json"), sort_keys=True,
                                                     ensure_ascii=False).encode()).hexdigest()[:16] + '"'
        return out, etag
