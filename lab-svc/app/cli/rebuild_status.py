"""Rebuilds or verifies patient_lab_status from lab_results (LLD B11.3).

Usage:
  python -m app.cli.rebuild_status                       # every patient
  python -m app.cli.rebuild_status --patient-id <uuid>   # one patient
  python -m app.cli.rebuild_status --stale-only          # rows whose rules_version differs from the code's
  python -m app.cli.rebuild_status --check               # no writes; exit 1 and list ids on any difference
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import uuid

from app.core.config import get_settings
from app.db.session import create_engine, create_sessionmaker
from app.services import status_rebuild


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--patient-id", "--patient", dest="patient", type=uuid.UUID)
    parser.add_argument("--stale-only", action="store_true")
    parser.add_argument("--check", action="store_true", help="compare only; write nothing")
    args = parser.parse_args(argv)
    settings = get_settings()
    engine = create_engine(settings)
    sm = create_sessionmaker(engine)
    try:
        if args.check:
            bad = await status_rebuild.check(sm, settings, patient=args.patient)
            for pid, cols in bad:
                print(f"DIFF {pid}: {', '.join(cols)}")
            print(f"check: {len(bad)} patient(s) differ")
            return 1 if bad else 0
        res = await status_rebuild.rebuild(sm, settings, patient=args.patient, stale_only=args.stale_only)
        print(f"rebuilt patient_lab_status for {res.rebuilt} patient(s), skipped {res.skipped}")
        return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
