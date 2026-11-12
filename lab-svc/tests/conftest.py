"""Shared fixtures. Phase 2 tests need no database except /ready (marked ``api``).

Tokens are signed by a throwaway RSA key whose public half is served through a stub JWKS fetch, so the
real JwksCache / verify_access_token code path is exercised end to end.
"""
from __future__ import annotations

import base64
import os
import time
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import date
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI

from app.core.config import Settings
from app.core.errors import NotFound
from app.core.security import Clinician, User, require_role
from app.domain.clock import FakeClock
from app.main import create_app
from app.services.jwks import JwksCache, _b64u_uint, thumbprint_kid
from app.services.patient_client import PatientBasic

load_dotenv()          # picks up LAB_TEST_DATABASE_URL from .env when running on the host

ISSUER, AUDIENCE = "nephro-auth", "nephro-api"


def make_settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = dict(
        lab_database_url=os.environ.get("LAB_TEST_DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x"),
        environment="test",
        jwks_min_refetch_s=0.0,
        _env_file=None,
    )
    base.update(overrides)
    return Settings(**base)


def jwk_for(key: rsa.RSAPrivateKey) -> dict[str, str]:
    pub = key.public_key()
    nums = pub.public_numbers()
    return {"kty": "RSA", "use": "sig", "alg": "RS256", "kid": thumbprint_kid(pub),
            "n": _b64u_uint(nums.n), "e": _b64u_uint(nums.e)}


@pytest.fixture(scope="session")
def rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def sign(rsa_key: rsa.RSAPrivateKey, clock: FakeClock) -> Callable[..., str]:
    kid = thumbprint_kid(rsa_key.public_key())

    def _sign(*, role: str = "clinician", sub: str | None = None, name: str | None = "Dr. Test",
              iss: str = ISSUER, aud: str = AUDIENCE, ttl: int = 900, key: rsa.RSAPrivateKey | None = None,
              kid_override: str | None = None, drop: tuple[str, ...] = ()) -> str:
        now = int(clock().timestamp())
        claims: dict[str, Any] = {"sub": sub or str(uuid.uuid4()), "role": role, "iss": iss, "aud": aud,
                                  "iat": now, "nbf": now, "exp": now + ttl}
        if name is not None:
            claims["name"] = name
        for k in drop:
            claims.pop(k, None)
        return jwt.encode(claims, key or rsa_key, algorithm="RS256", headers={"kid": kid_override or kid})

    return _sign


@pytest.fixture
def jwks(rsa_key: rsa.RSAPrivateKey, settings: Settings) -> JwksCache:
    async def fetch() -> dict:
        return {"keys": [jwk_for(rsa_key)]}

    return JwksCache(fetch, settings, mono=time.monotonic)


class FakePatients:
    """Stands in for patient-svc GET /internal/patients/{id}/basic."""

    def __init__(self) -> None:
        self.people: dict[uuid.UUID, PatientBasic] = {}
        self.error: Exception | None = None
        self.calls: list[tuple[uuid.UUID, str, str | None]] = []

    def add(self, sex: str = "M", dob: date = date(1959, 4, 17)) -> uuid.UUID:
        pid = uuid.uuid4()
        self.people[pid] = PatientBasic(sex, dob)
        return pid

    async def basic(self, patient_id: uuid.UUID, authorization: str, request_id: str | None) -> PatientBasic:
        self.calls.append((patient_id, authorization, request_id))
        if self.error:
            raise self.error
        if patient_id not in self.people:
            raise NotFound()
        return self.people[patient_id]


@pytest.fixture
def patients() -> FakePatients:
    return FakePatients()


@pytest.fixture
def app(settings: Settings, clock: FakeClock, jwks: JwksCache, patients: FakePatients) -> FastAPI:
    app = create_app(settings, clock=clock, jwks=jwks, patients=patients)
    # A probe route proves the auth dependencies independently of business routes.
    probe = APIRouter()

    @probe.get("/_probe/me")
    async def me(user: Clinician) -> dict:
        return {"id": str(user.id)}

    @probe.get("/_probe/admin")
    async def admin(_: User = Depends(require_role("admin"))) -> dict:
        return {"ok": True}

    app.include_router(probe)
    return app


@pytest.fixture
async def client(app: FastAPI, jwks: JwksCache) -> AsyncIterator[httpx.AsyncClient]:
    async with app.router.lifespan_context(app):
        await jwks.refresh("test")
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


# =============================================================================================
# Database fixtures: real Postgres test database (nephro_lab_db_test on the shared container)
# =============================================================================================
import subprocess  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
# Only the data tables are cleared; the catalog (lab_tests, lab_reference_ranges) is reference data.
TABLES = "audit_events, patient_lab_status, lab_results, lab_reports"


@pytest.fixture(scope="session")
def migrated_db() -> str:
    """Runs ``alembic upgrade head`` once per session against the TEST database and returns its URL."""
    url = os.environ.get("LAB_TEST_DATABASE_URL")
    if not url:
        if os.environ.get("REQUIRE_DB_TESTS") == "1":
            # CI sets this, so a misconfigured pipeline FAILS instead of quietly skipping the API and DB tests
            pytest.fail("LAB_TEST_DATABASE_URL is not set but REQUIRE_DB_TESTS=1", pytrace=False)
        pytest.skip("LAB_TEST_DATABASE_URL not set")
    env = {**os.environ, "LAB_DATABASE_URL": url}
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, env=env, check=True,
                   capture_output=True)
    subprocess.run([sys.executable, "-m", "app.cli.seed_catalog"], cwd=ROOT, env={**env, "LAB_DATABASE_URL": url},
                   check=True, capture_output=True)
    return url


@pytest.fixture
async def db_engine(migrated_db: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(migrated_db)
    async with engine.begin() as conn:      # TRUNCATE does not fire row triggers (tests only, LLD §9.3)
        await conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
    yield engine
    await engine.dispose()
