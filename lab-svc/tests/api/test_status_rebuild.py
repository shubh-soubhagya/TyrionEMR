"""Phase 7: the read model (LLD B3.6, B6.3) and the rebuild / check script (B11.3)."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.cli import rebuild_status
from app.services import status_rebuild
from tests.conftest import make_settings

pytestmark = pytest.mark.api
BASE = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
UNITS = {"CREAT": "mg/dL", "EGFR": "mL/min/1.73m²", "K": "mmol/L", "UACR": "mg/g"}


def stamp(days: int) -> str:
    return (BASE + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


async def add(api: httpx.AsyncClient, pid, day: int, **vals: float) -> dict:
    resp = await api.post(f"/labs/patients/{pid}/reports", json={
        "collected_at": stamp(day), "results": [{"test_code": k, "value": v, "unit": UNITS[k]} for k, v in vals.items()]})
    assert resp.status_code == 201, resp.text
    return resp.json()


async def status_row(db_engine, pid) -> dict:
    async with db_engine.connect() as c:
        return dict((await c.execute(text("SELECT * FROM patient_lab_status WHERE patient_id = :p"), {"p": pid}))
                    .mappings().one())


@pytest.fixture
def sm(db_engine):
    return async_sessionmaker(db_engine, expire_on_commit=False)


async def populate(api, patients, n: int = 3) -> list[uuid.UUID]:
    ids = []
    for i in range(n):
        pid = patients.add("M" if i % 2 == 0 else "F")
        for day, (e, c) in enumerate([(60, 1.3), (56, 1.5), (52, 1.7), (48, 1.9)]):
            await add(api, pid, day * 30, EGFR=e - i, CREAT=c)
        await add(api, pid, 130, K=6.4 if i == 0 else 4.2, UACR=250 + i)
        ids.append(pid)
    return ids


async def test_version_increases_by_one_per_write_and_counts_current_results(api, patients, db_engine) -> None:
    pid = patients.add()
    await add(api, pid, 0, K=4.0)
    first = await status_row(db_engine, pid)
    assert (first["version"], first["result_count"], first["rules_version"]) == (1, 1, "lab-rules-1")
    res = (await add(api, pid, 10, K=6.8, UACR=100))["results"][0]
    second = await status_row(db_engine, pid)
    assert (second["version"], second["result_count"]) == (2, 3)
    await api.post(f"/labs/results/{res['id']}/correct", json={"value": 4.4, "unit": "mmol/L", "reason": "re-keyed"})
    third = await status_row(db_engine, pid)
    assert (third["version"], third["result_count"]) == (3, 3)               # a correction replaces, never adds


async def test_back_dated_report_does_not_replace_the_latest(api, patients) -> None:
    pid = patients.add()
    await add(api, pid, 100, K=4.0)
    await add(api, pid, 10, K=6.9)                                           # entered later, collected earlier
    latest = (await api.get(f"/labs/patients/{pid}/latest")).json()
    assert latest["latest"]["K"]["value"] == 4.0 and latest["has_critical"] is False


async def test_latest_snapshot_carries_the_reference_limits(api, patients) -> None:
    pid = patients.add("M")
    await add(api, pid, 0, CREAT=1.8)
    entry = (await api.get(f"/labs/patients/{pid}/latest")).json()["latest"]["CREAT"]
    assert (entry["ref_low"], entry["ref_high"], entry["flag"]) == (0.7, 1.3, "high")


async def test_rebuild_reproduces_the_incremental_state(api, patients, db_engine, sm) -> None:
    ids = await populate(api, patients)
    before = {p: await status_row(db_engine, p) for p in ids}
    async with db_engine.begin() as c:
        await c.execute(text("TRUNCATE patient_lab_status"))
    res = await status_rebuild.rebuild(sm, make_settings())
    assert res.rebuilt == len(ids)
    for p in ids:
        after = await status_row(db_engine, p)
        for col in status_rebuild.COMPARED:
            assert after[col] == before[p][col], col
        assert after["version"] == 1                                         # a fresh row: version restarts


async def test_check_passes_after_the_suite_style_writes(api, patients, sm) -> None:
    await populate(api, patients)
    assert await status_rebuild.check(sm, make_settings()) == []


async def test_check_reports_a_tampered_row_and_writes_nothing(api, patients, db_engine, sm) -> None:
    a, b, _ = await populate(api, patients)
    async with db_engine.begin() as c:
        await c.execute(text("UPDATE patient_lab_status SET has_critical = NOT has_critical, result_count = 99 "
                             "WHERE patient_id = :p"), {"p": a})
    before = await status_row(db_engine, a)
    bad = await status_rebuild.check(sm, make_settings())
    assert [(p, sorted(cols)) for p, cols in bad] == [(a, ["has_critical", "result_count"])] and b not in {p for p, _ in bad}
    assert await status_row(db_engine, a) == before                          # check never writes


async def test_check_detects_missing_and_orphan_rows(api, patients, db_engine, sm) -> None:
    a, b, _ = await populate(api, patients)
    ghost = uuid.uuid4()
    async with db_engine.begin() as c:
        await c.execute(text("DELETE FROM patient_lab_status WHERE patient_id = :p"), {"p": a})
        await c.execute(text("INSERT INTO patient_lab_status (patient_id, rules_version) VALUES (:p, 'x')"), {"p": ghost})
    bad = dict(await status_rebuild.check(sm, make_settings()))
    assert bad[a] == ["<missing row>"] and bad[ghost] == ["<orphan row>"] and b not in bad


async def test_stale_only_recomputes_just_the_rows_built_with_old_rules(api, patients, db_engine, sm) -> None:
    a, b, c = await populate(api, patients)
    async with db_engine.begin() as conn:
        await conn.execute(text("UPDATE patient_lab_status SET rules_version = 'lab-rules-0' WHERE patient_id = :p"), {"p": b})
    versions = {p: (await status_row(db_engine, p))["version"] for p in (a, b, c)}
    res = await status_rebuild.rebuild(sm, make_settings(), stale_only=True)
    assert (res.rebuilt, res.skipped) == (1, 2)
    after = {p: await status_row(db_engine, p) for p in (a, b, c)}
    assert after[b]["rules_version"] == "lab-rules-1" and after[b]["version"] == versions[b] + 1
    assert after[a]["version"] == versions[a] and after[c]["version"] == versions[c]       # untouched


async def test_single_patient_rebuild(api, patients, db_engine, sm) -> None:
    a, b, _ = await populate(api, patients)
    va, vb = (await status_row(db_engine, a))["version"], (await status_row(db_engine, b))["version"]
    assert (await status_rebuild.rebuild(sm, make_settings(), patient=a)).rebuilt == 1
    assert (await status_row(db_engine, a))["version"] == va + 1 and (await status_row(db_engine, b))["version"] == vb


async def test_patients_are_streamed_in_id_order_across_pages(api, patients, sm) -> None:
    ids = await populate(api, patients, n=5)
    seen = [p async for p in status_rebuild.patient_ids(sm, page=2)]
    assert seen == sorted(ids)


async def test_cli_exit_codes(api, patients, db_engine, monkeypatch) -> None:
    pids = await populate(api, patients, n=2)
    import os
    monkeypatch.setenv("LAB_DATABASE_URL", os.environ["LAB_TEST_DATABASE_URL"])
    from app.core.config import get_settings
    get_settings.cache_clear()
    try:
        assert await rebuild_status.main(["--check"]) == 0
        async with db_engine.begin() as c:
            await c.execute(text("UPDATE patient_lab_status SET egfr_category = 'G1' WHERE patient_id = :p"), {"p": pids[0]})
        assert await rebuild_status.main(["--check"]) == 1
        assert await rebuild_status.main(["--patient-id", str(pids[0])]) == 0
        assert await rebuild_status.main(["--check"]) == 0
    finally:
        get_settings.cache_clear()


async def test_attention_partial_index_serves_the_worklist(db_engine) -> None:
    async with db_engine.connect() as c:
        idx = (await c.execute(text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_status_attention'"))).scalar_one()
    assert "WHERE (has_critical OR rapid_decline)" in idx
