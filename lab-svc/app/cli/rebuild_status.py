"""Rebuilds patient_lab_status for every patient (or one) from lab_results.

The read model is derived data: this recomputes it with the SAME function the write path uses, so after a
rebuild it equals the incrementally maintained state. Safe to run at any time; each patient is one transaction.

Usage: python -m app.cli.rebuild_status [--patient <uuid>]
"""
from __future__ import annotations

import argparse
import asyncio
import uuid

from app.core.config import get_settings
from app.db.session import create_engine, create_sessionmaker
from app.repositories.labs import LabRepository
from app.services.reports import refresh_status


async def rebuild(sessionmaker, settings, only: uuid.UUID | None = None) -> int:
    async with sessionmaker() as session, session.begin():
        ids = [only] if only else await LabRepository(session).patients_with_results()
    for pid in ids:
        async with sessionmaker() as session, session.begin():
            repo = LabRepository(session)
            await repo.lock_patient(pid)
            await refresh_status(repo, pid, settings.trend_config(), settings.spark_points)
    return len(ids)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--patient", type=uuid.UUID)
    args = parser.parse_args()
    settings = get_settings()
    engine = create_engine(settings)
    try:
        n = await rebuild(create_sessionmaker(engine), settings, args.patient)
        print(f"rebuilt patient_lab_status for {n} patient(s)")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
