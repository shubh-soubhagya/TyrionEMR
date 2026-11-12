"""Runs the stale-job reaper once (B18.11 troubleshooting: `make reap`). Safe next to a running service."""
from __future__ import annotations

import asyncio
import sys

from app.core.config import get_settings
from app.db.session import create_engine, create_sessionmaker
from app.jobs.reaper import reap_once


async def main() -> int:
    s = get_settings()
    engine = create_engine(s)
    try:
        ids = await reap_once(create_sessionmaker(engine), s.llm_job_ttl_s)
        print(f"reaped {len(ids)} job(s)")
        return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
