from __future__ import annotations

import httpx
import pytest

pytestmark = pytest.mark.api


async def test_catalog_has_all_eight_tests_in_order(api: httpx.AsyncClient) -> None:
    r = await api.get("/labs/tests", params={"sex": "M"})
    assert r.status_code == 200
    assert [t["code"] for t in r.json()["tests"]] == ["CREAT", "EGFR", "BUN", "K", "HB", "CA", "PHOS", "UACR"]


async def test_creatinine_lists_both_units_with_factors(api: httpx.AsyncClient) -> None:
    t = next(t for t in (await api.get("/labs/tests", params={"sex": "M"})).json()["tests"] if t["code"] == "CREAT")
    assert t["canonical_unit"] == "mg/dL"
    assert {u["unit"]: u["factor"] for u in t["allowed_units"]} == {"mg/dL": 1, "µmol/L": 0.0113}
    assert t["decimals"] == 2


async def test_range_depends_on_sex(api: httpx.AsyncClient) -> None:
    def creat(body: dict) -> dict:
        return next(t for t in body["tests"] if t["code"] == "CREAT")["reference_range"]

    m = creat((await api.get("/labs/tests", params={"sex": "M"})).json())
    f = creat((await api.get("/labs/tests", params={"sex": "F"})).json())
    assert (m["low"], m["high"], m["critical_high"], m["text"]) == (0.7, 1.3, 5.0, "0.7–1.3")
    assert (f["low"], f["high"], f["text"]) == (0.6, 1.1, "0.6–1.1")


async def test_one_sided_ranges_render_like_the_prototype(api: httpx.AsyncClient) -> None:
    tests = {t["code"]: t for t in (await api.get("/labs/tests", params={"sex": "F"})).json()["tests"]}
    assert tests["EGFR"]["reference_range"]["text"] == "≥ 90"
    assert tests["EGFR"]["reference_range"]["critical_low"] == 10
    assert tests["UACR"]["reference_range"]["text"] == "< 30"
    assert tests["K"]["reference_range"]["text"] == "3.5–5"


async def test_without_sex_sex_specific_tests_have_no_range(api: httpx.AsyncClient) -> None:
    """Missing is explicit (null), never a guessed or "normal" range."""
    tests = {t["code"]: t for t in (await api.get("/labs/tests")).json()["tests"]}
    assert tests["CREAT"]["reference_range"] is None and tests["HB"]["reference_range"] is None
    assert tests["K"]["reference_range"] is not None


async def test_invalid_sex_is_422(api: httpx.AsyncClient) -> None:
    r = await api.get("/labs/tests", params={"sex": "X"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_requires_authentication(client: httpx.AsyncClient) -> None:
    r = await client.get("/labs/tests")
    assert r.status_code == 401


async def test_seed_is_idempotent(api: httpx.AsyncClient, db_engine) -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.cli.seed_catalog import seed_catalog

    async def counts() -> tuple[int, int]:
        async with db_engine.connect() as c:
            return ((await c.execute(text("SELECT count(*) FROM lab_tests"))).scalar_one(),
                    (await c.execute(text("SELECT count(*) FROM lab_reference_ranges"))).scalar_one())

    before = await counts()
    async with async_sessionmaker(db_engine)() as s:
        await seed_catalog(s)
        await seed_catalog(s)
    assert await counts() == before == (8, 10)
