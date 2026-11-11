"""Retry ``SELECT 1`` until the database answers (the Postgres container is external, so compose
cannot wait on it). Exits non-zero after DB_WAIT_ATTEMPTS tries, 2 s apart."""
from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings


async def main() -> int:
    s = get_settings()
    engine = create_async_engine(s.auth_database_url, connect_args={"timeout": 3})
    try:
        for attempt in range(1, s.db_wait_attempts + 1):
            try:
                async with engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))
                print(f"database reachable (attempt {attempt})")
                return 0
            except Exception as exc:       # print the type only: messages can contain the DSN
                print(f"waiting for database ({attempt}/{s.db_wait_attempts}): {type(exc).__name__}")
                await asyncio.sleep(2)
        print("database never became reachable", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
