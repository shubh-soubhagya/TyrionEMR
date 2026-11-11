"""Shared fixtures. Unit tests need no DB; API fixtures (added with the API tests) use the real test DB."""
from __future__ import annotations

import os

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.config import Settings
from app.domain.clock import FakeClock


def make_settings(**overrides) -> Settings:
    base = dict(
        auth_database_url=os.environ.get("AUTH_TEST_DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x"),
        jwt_private_key_path="unused",
        argon2_time_cost=1, argon2_memory_kib=1024, argon2_parallelism=1,   # cheap hashing in tests (LLD §25)
        cookie_secure=True,
        _env_file=None,
    )
    base.update(overrides)
    return Settings(**base)


@pytest.fixture(scope="session")
def rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()
