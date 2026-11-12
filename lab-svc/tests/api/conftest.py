"""API-test fixtures: real test database (data tables truncated before every test), fixed clock, tokens."""
from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime

import httpx
import pytest

from app.domain.clock import FakeClock

FIXED_NOW = datetime(2026, 11, 11, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(FIXED_NOW)


@pytest.fixture
async def api(client: httpx.AsyncClient, db_engine, sign: Callable[..., str]) -> AsyncIterator[httpx.AsyncClient]:
    client.headers["Authorization"] = f"Bearer {sign()}"
    yield client
