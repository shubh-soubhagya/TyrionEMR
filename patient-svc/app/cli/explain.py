"""Captures EXPLAIN (ANALYZE, BUFFERS) for the queries of LLD §26 into docs/db/explain/.

Run it against a database filled by ``python -m app.cli.seed_patients --scale 10000``. The real repository
functions run first; a SQLAlchemy event records the exact SQL and parameters each one sends, and that same
statement is then re-run under EXPLAIN, so the plans are those of the code, not of a hand-copied query.
"""
from __future__ import annotations

import asyncio
import sys
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from sqlalchemy import event, text

from app.core.config import get_settings
from app.db.session import create_engine
from app.domain.clock import utcnow
from app.domain.search import parse_query
from app.repositories import encounters as enc_repo
from app.repositories import internal as internal_repo
from app.repositories import patients as patients_repo

OUT = Path(__file__).resolve().parents[2] / "docs" / "db" / "explain"


async def main() -> int:
    settings = get_settings()
    if settings.environment == "production":
        print("Refusing: ENVIRONMENT=production.", file=sys.stderr)
        return 1
    engine = create_engine(settings)
    captured: list[tuple[str, tuple]] = []

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def _capture(conn, cursor, statement, parameters, context, executemany):    # noqa: ANN001
        captured.append((statement, tuple(parameters) if not isinstance(parameters, dict) else parameters))

    today = utcnow().date()
    async with engine.connect() as conn:
        some_patient = (await conn.execute(text("SELECT id FROM patients ORDER BY id OFFSET 500 LIMIT 1"))).scalar_one()
        total = (await conn.execute(text("SELECT count(*) FROM patients"))).scalar_one()
        enc_total = (await conn.execute(text("SELECT count(*) FROM encounters"))).scalar_one()

    async def run(session, name: str, call: Callable[[], Awaitable]) -> tuple[str, str, tuple]:
        captured.clear()
        await call()
        # the main statement is the longest one the call sent
        statement, params = max(captured, key=lambda c: len(c[0]))
        return name, statement, params

    list_kw: dict[str, Any] = dict(sex=None, stage=None, ids=None, direction="asc", page=1, size=8, today=today)
    async with engine.connect() as session_conn:
        from sqlalchemy.ext.asyncio import AsyncSession
        s = AsyncSession(bind=session_conn)
        cases = [
            ("list_name_sort_page1", lambda: patients_repo.list_patients(
                s, search=parse_query(None), sort="name", **list_kw)),
            ("list_sort_by_visit", lambda: patients_repo.list_patients(
                s, search=parse_query(None), sort="visit", **{**list_kw, "direction": "desc"})),
            ("list_sort_by_primary_dx", lambda: patients_repo.list_patients(
                s, search=parse_query(None), sort="dx", **list_kw)),
            ("search_name_token", lambda: patients_repo.list_patients(
                s, search=parse_query("last42 first"), sort="name", **list_kw)),
            ("search_mrn", lambda: patients_repo.list_patients(
                s, search=parse_query("PT-000500"), sort="name", **list_kw)),
            ("patient_detail_extras", lambda: patients_repo.detail_extras(s, some_patient, today)),
            ("encounter_history", lambda: enc_repo.history(s, some_patient, None, 1, 20)),
            ("dashboard_followups", lambda: enc_repo.upcoming_followups(s, today, 5)),
            ("dashboard_drafts", lambda: enc_repo.drafts(s, 10)),
            ("internal_bulk_page_200", lambda: internal_repo.bulk_charts(s, None, 200, today)),
            ("internal_basic", lambda: internal_repo.basic(s, uuid.UUID(str(some_patient)))),
        ]
        OUT.mkdir(parents=True, exist_ok=True)
        summary = [f"Data set: {total} patients, {enc_total} encounters.\n"]
        for name, call in cases:
            _, statement, params = await run(s, name, call)
            async with engine.connect() as c:
                rows = await c.exec_driver_sql(f"EXPLAIN (ANALYZE, BUFFERS) {statement}", params)
                plan = "\n".join(r[0] for r in rows)
            (OUT / f"{name}.txt").write_text(plan + "\n", encoding="utf-8")
            exec_line = next((ln for ln in plan.splitlines() if "Execution Time" in ln), "")
            summary.append(f"{name:28s} {exec_line.strip()}")
        await s.close()
    (OUT / "README.txt").write_text("\n".join(summary) + "\n", encoding="utf-8")
    print("\n".join(summary))
    await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
