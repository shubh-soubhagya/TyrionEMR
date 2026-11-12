"""Captures EXPLAIN (ANALYZE, BUFFERS) for the hot queries into docs/db/explain/.

TEST DATABASE ONLY: it refuses production and any database whose name does not end in ``_test``, because it
empties the lab tables and loads synthetic volume (default 10,000 patients x 20 results = 200,000 rows, written
with SQL generate_series, bypassing the service on purpose: this measures the read queries, not the write path).

The real repository functions run first; a SQLAlchemy event records the exact SQL each sends, and that same
statement is re-run under EXPLAIN, so the plans are those of the code and not of a hand-copied query.

Usage (with LAB_DATABASE_URL pointing at the test database): python -m app.cli.explain [--patients N]
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import create_engine
from app.repositories.labs import LabRepository

OUT = Path(__file__).resolve().parents[2] / "docs" / "db" / "explain"
PER_PATIENT = 20
PAGE1: dict[str, Any] = {"test": None, "date_from": None, "date_to": None, "include_superseded": False,
                         "offset": 0, "limit": 50}

LOAD = """
WITH p AS MATERIALIZED (SELECT gen_random_uuid() AS id FROM generate_series(1, :n))
INSERT INTO lab_reports (id, patient_id, collected_at, lab_name, entered_by, created_at)
SELECT gen_random_uuid(), p.id, now() - (g * interval '20 days'), 'Synthetic lab', p.id, now()
FROM p, generate_series(1, :k) g
"""
LOAD_RESULTS = """
INSERT INTO lab_results (report_id, patient_id, collected_at, test_code, value, unit, value_original,
                         unit_original, range_id, flag, entered_by, created_at)
SELECT r.id, r.patient_id, r.collected_at, 'EGFR', 40 + (random() * 40)::numeric(6,1), 'mL/min/1.73m2',
       50, 'mL/min/1.73m2', (SELECT id FROM lab_reference_ranges WHERE test_code = 'EGFR'),
       CASE WHEN random() < 0.7 THEN 'low' ELSE 'normal' END, r.entered_by, now()
FROM lab_reports r
"""
LOAD_STATUS = """
INSERT INTO patient_lab_status (patient_id, latest, egfr_category, egfr_spark, has_critical, rapid_decline,
                               result_count, last_result_at, rules_version)
SELECT patient_id, '{}'::jsonb, 'G3b', '[]'::jsonb, false, false, count(*), now(), 'lab-rules-1'
FROM lab_results GROUP BY patient_id
"""


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--patients", type=int, default=10_000)
    args = parser.parse_args()
    settings = get_settings()
    db_name = settings.lab_database_url.rsplit("/", 1)[-1].split("?")[0]
    if settings.environment == "production" or not db_name.endswith("_test"):
        print(f"Refusing: {db_name!r} is not a *_test database.", file=sys.stderr)
        return 1
    engine = create_engine(settings)
    captured: list[tuple[str, Any]] = []

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def _capture(conn, cursor, statement, parameters, context, executemany):    # noqa: ANN001
        captured.append((statement, parameters))

    async with engine.begin() as conn:
        await conn.execute(text("SET LOCAL statement_timeout = 0"))        # bulk load only
        await conn.execute(text("TRUNCATE patient_lab_status, lab_results, lab_reports, audit_events"))
        await conn.execute(text(LOAD), {"n": args.patients, "k": PER_PATIENT})
        await conn.execute(text(LOAD_RESULTS))
        await conn.execute(text(LOAD_STATUS))
        await conn.execute(text("ANALYZE lab_reports, lab_results, patient_lab_status"))
        pid = (await conn.execute(text("SELECT patient_id FROM lab_results OFFSET 5000 LIMIT 1"))).scalar_one()
        ids = [r[0] for r in (await conn.execute(text("SELECT patient_id FROM patient_lab_status LIMIT 50")))]
        n_results = (await conn.execute(text("SELECT count(*) FROM lab_results"))).scalar_one()

    async def run(name: str, call: Callable[[], Awaitable]) -> tuple[str, str, Any]:
        captured.clear()
        await call()
        statement, params = max(captured, key=lambda c: len(c[0]))     # the main statement of the call
        return name, statement, params

    async with engine.connect() as conn:
        s = AsyncSession(bind=conn)
        repo = LabRepository(s)
        cases = [
            ("results_history_page1", lambda: repo.list_results(pid, flag=None, **PAGE1)),
            ("results_abnormal_only", lambda: repo.list_results(pid, flag="abnormal", **PAGE1)),
            ("trend_series_egfr", lambda: repo.series(pid, ["EGFR"], None, None)),
            ("status_by_primary_key", lambda: repo.status(pid)),
            ("summary_50_ids", lambda: repo.statuses(ids)),
            ("bulk_status_page", lambda: repo.status_page(ids[0], 200)),
            ("effective_points_rebuild", lambda: repo.effective_points(pid)),
        ]
        plans = [await run(n, c) for n, c in cases]
        await s.close()

    OUT.mkdir(parents=True, exist_ok=True)
    async with engine.connect() as conn:
        raw = await conn.get_raw_connection()
        pg: Any = raw.driver_connection
        for name, statement, params in plans:
            pg_sql, args_ = _to_asyncpg(statement, params)
            rows = await pg.fetch("EXPLAIN (ANALYZE, BUFFERS) " + pg_sql, *args_)
            plan = "\n".join(r[0] for r in rows)
            (OUT / f"{name}.txt").write_text(
                f"-- {args.patients} patients, {n_results} results\n-- {pg_sql}\n\n{plan}\n", encoding="utf-8")
            print(f"{name}: {rows[-1][0]}")
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE patient_lab_status, lab_results, lab_reports, audit_events"))
    await engine.dispose()
    return 0


def _to_asyncpg(statement: str, params: Any) -> tuple[str, list]:
    """The SQLAlchemy asyncpg dialect already emits $1, $2 placeholders; params arrive as a tuple."""
    values = list(params) if isinstance(params, (tuple, list)) else list(params.values())
    return statement, [v if not isinstance(v, uuid.UUID) else v for v in values]


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
