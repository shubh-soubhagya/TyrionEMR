"""Shared fixtures. Tests run in-process: no Docker, no network, no real clock."""
from __future__ import annotations

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI

from app.core.config import Settings
from app.domain.clock import FakeClock
from app.main import create_app


@pytest.fixture(scope="session")
def rsa_private_key() -> rsa.RSAPrivateKey:
    # One 2048-bit key for the whole session: generation is the slow part. Phase 3 adds token helpers.
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def make_settings():
    def factory(**overrides: object) -> Settings:
        # _env_file=None: a developer's local .env must never change test results
        return Settings(_env_file=None, environment="test", **overrides)  # type: ignore[call-arg]

    return factory


@pytest.fixture
def settings(make_settings) -> Settings:
    return make_settings()


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
async def client(app: FastAPI):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://gateway.test") as c:
        yield c
