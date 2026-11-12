"""API/DB fixtures: the real test database nephro_ai_db_test on the shared Postgres container."""
from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

ROOT = Path(__file__).resolve().parents[2]
TABLES = "llm_tool_calls, ai_summaries"      # TRUNCATE does not fire row triggers (tests only, B3.4)


@pytest.fixture(scope="session")
def migrated_db() -> str:
    url = os.environ.get("AI_TEST_DATABASE_URL")
    if not url:
        if os.environ.get("REQUIRE_DB_TESTS") == "1":
            pytest.fail("AI_TEST_DATABASE_URL is not set but REQUIRE_DB_TESTS=1", pytrace=False)
        pytest.skip("AI_TEST_DATABASE_URL not set")
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT,
                   env={**os.environ, "AI_DATABASE_URL": url}, check=True, capture_output=True)
    return url


@pytest.fixture
async def db_engine(migrated_db: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(migrated_db)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
    yield engine
    await engine.dispose()
