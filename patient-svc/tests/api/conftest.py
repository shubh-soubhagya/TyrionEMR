"""API-test fixtures: real test database (truncated before every test), fixed clock, signed clinician tokens."""
from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from app.domain.clock import FakeClock

# 12:00 UTC on 2026-11-11 = 17:30 IST: "today" is 2026-11-11 in CLINIC_TZ
FIXED_NOW = datetime(2026, 11, 11, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(FIXED_NOW)


@pytest.fixture
async def api(client: httpx.AsyncClient, db_engine, sign: Callable[..., str]) -> AsyncIterator[httpx.AsyncClient]:
    client.headers["Authorization"] = f"Bearer {sign()}"
    yield client


@pytest.fixture
def make_patient(api: httpx.AsyncClient) -> Callable[..., Any]:
    async def _make(**overrides: Any) -> dict:
        body = {"first_name": "Ramesh", "last_name": "Kulkarni", "date_of_birth": "1959-04-17", "sex": "M"}
        body.update(overrides)
        r = await api.post("/patients", json=body)
        assert r.status_code == 201, r.text
        return r.json()

    return _make
