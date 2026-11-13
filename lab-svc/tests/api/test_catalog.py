"""Phase 5: GET /labs/tests (LLD B7.1), the catalog cache (B6.9) and the idempotent seed."""
from __future__ import annotations

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.cli.seed_catalog import seed_catalog
from app.services.catalog import CatalogCache

pytestmark = pytest.mark.api


def by_code(body: dict) -> dict[str, dict]:
    return {t["code"]: t for t in body["items"]}


async def test_catalog_has_all_eight_tests_in_display_order(api: httpx.AsyncClient) -> None:
    body = (await api.get("/labs/tests", params={"sex": "M"})).json()
    assert [t["code"] for t in body["items"]] == ["CREAT", "EGFR", "BUN", "K", "HB", "CA", "PHOS", "UACR"]
    assert [t["display_order"] for t in body["items"]] == list(range(1, 9))
    assert body["rules_version"] == "lab-rules-2"


async def test_units_carry_exact_string_factors(api: httpx.AsyncClient) -> None:
    t = by_code((await api.get("/labs/tests", params={"sex": "M"})).json())["CREAT"]
    assert t["canonical_unit"] == "mg/dL" and t["decimals"] == 2 and t["plausible_max"] == 30
    assert t["units"] == [{"unit": "mg/dL", "factor": "1"}, {"unit": "µmol/L", "factor": "0.0113"}]


async def test_range_depends_on_sex(api: httpx.AsyncClient) -> None:
    m = by_code((await api.get("/labs/tests", params={"sex": "M"})).json())["CREAT"]["range"]
    f = by_code((await api.get("/labs/tests", params={"sex": "F"})).json())["CREAT"]["range"]
    assert (m["low"], m["high"], m["critical_high"], m["text"]) == (0.7, 1.3, 5.0, "0.7–1.3")
    assert (f["low"], f["high"], f["text"]) == (0.6, 1.1, "0.6–1.1")
    assert m["range_id"] and m["range_id"] != f["range_id"]


async def test_one_sided_ranges_render_like_the_prototype(api: httpx.AsyncClient) -> None:
    tests = by_code((await api.get("/labs/tests", params={"sex": "F"})).json())
    assert tests["EGFR"]["range"]["text"] == "≥ 90" and tests["EGFR"]["range"]["critical_low"] == 10
    assert tests["UACR"]["range"]["text"] == "< 30"
    assert tests["K"]["range"]["text"] == "3.5–5"


async def test_sex_other_has_no_range_for_sex_specific_tests(api: httpx.AsyncClient) -> None:
    """Missing is explicit (null), never a guessed range: the preview shows "No range"."""
    tests = by_code((await api.get("/labs/tests", params={"sex": "O"})).json())
    assert tests["CREAT"]["range"] is None and tests["HB"]["range"] is None
    assert tests["K"]["range"] is not None and tests["EGFR"]["range"] is not None


async def test_without_sex_every_range_is_listed(api: httpx.AsyncClient) -> None:
    tests = by_code((await api.get("/labs/tests")).json())
    assert tests["CREAT"]["range"] is None
    assert sorted(r["sex"] for r in tests["CREAT"]["ranges"]) == ["F", "M"]
    assert [r["sex"] for r in tests["K"]["ranges"]] == [None]


async def test_age_is_accepted_with_sex_only(api: httpx.AsyncClient) -> None:
    assert (await api.get("/labs/tests", params={"sex": "M", "age": 67})).status_code == 200
    r = await api.get("/labs/tests", params={"age": 67})
    assert r.status_code == 422 and r.json()["error"]["details"][0]["field"] == "age"
    assert (await api.get("/labs/tests", params={"sex": "M", "age": 200})).status_code == 422


async def test_invalid_sex_is_422(api: httpx.AsyncClient) -> None:
    r = await api.get("/labs/tests", params={"sex": "X"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_requires_authentication(client: httpx.AsyncClient) -> None:
    assert (await client.get("/labs/tests")).status_code == 401


async def test_etag_and_cache_headers_and_304(api: httpx.AsyncClient) -> None:
    first = await api.get("/labs/tests", params={"sex": "M"})
    etag = first.headers["etag"]
    assert etag.startswith('W/"cat-') and first.headers["cache-control"] == "private, max-age=300"
    again = await api.get("/labs/tests", params={"sex": "M"}, headers={"If-None-Match": etag})
    assert again.status_code == 304 and again.content == b"" and again.headers["etag"] == etag
    other = await api.get("/labs/tests", params={"sex": "F"})
    assert other.headers["etag"] != etag                                  # a different view has a different tag
    stale = await api.get("/labs/tests", params={"sex": "M"}, headers={"If-None-Match": 'W/"cat-0000"'})
    assert stale.status_code == 200


async def test_seed_is_idempotent(api: httpx.AsyncClient, db_engine) -> None:
    async def counts() -> tuple[int, int]:
        async with db_engine.connect() as c:
            return ((await c.execute(text("SELECT count(*) FROM lab_tests"))).scalar_one(),
                    (await c.execute(text("SELECT count(*) FROM lab_reference_ranges"))).scalar_one())

    before = await counts()
    async with async_sessionmaker(db_engine)() as s:
        await seed_catalog(s)
        await seed_catalog(s)
    assert await counts() == before == (8, 10)


async def test_every_seeded_range_names_its_source(db_engine) -> None:
    async with db_engine.connect() as c:
        rows = (await c.execute(text("SELECT DISTINCT source FROM lab_reference_ranges"))).all()
    assert rows and all(r[0].strip() for r in rows)


# ---- cache (B6.9) --------------------------------------------------------------------------------
async def test_cache_reloads_after_the_ttl_and_keeps_serving_when_a_reload_fails(db_engine) -> None:
    now = [0.0]
    cache = CatalogCache(async_sessionmaker(db_engine), ttl_s=300, mono=lambda: now[0])
    assert not cache.loaded
    first = await cache.get()
    assert cache.loaded and len(first.tests) == 8 and first.by_code["K"].units["mEq/L"] == 1
    assert await cache.get() is first                                       # within the TTL: same object
    now[0] = 301
    assert await cache.get() is not first                                   # expired: reloaded
    cache._sm = lambda: (_ for _ in ()).throw(RuntimeError("db down"))      # type: ignore[assignment]
    now[0] = 700
    assert (await cache.get()).by_code["K"].code == "K"                     # failed reload serves the old copy
    cache.invalidate()
    assert (await cache.get()).by_code["K"].code == "K"


async def test_first_load_failure_is_a_503_not_a_crash() -> None:
    from app.core.errors import DbUnavailable
    cache = CatalogCache(lambda: (_ for _ in ()).throw(RuntimeError("db down")), 300)    # type: ignore[arg-type]
    with pytest.raises(DbUnavailable):
        await cache.get()
    assert not cache.loaded


async def test_ready_fails_until_the_catalog_is_loaded(client, app, migrated_db) -> None:
    cache = app.state.catalog
    good_sm = cache._sm
    cache._catalog = None
    cache._sm = lambda: (_ for _ in ()).throw(RuntimeError("db down"))
    r = await client.get("/ready")
    assert r.status_code == 503 and {"check": "catalog", "status": "failed"} in r.json()["error"]["details"]
    cache._sm = good_sm
    assert (await client.get("/ready")).status_code == 200                  # self-heals on the next probe
