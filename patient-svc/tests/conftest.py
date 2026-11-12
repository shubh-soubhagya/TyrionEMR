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
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI, Request

from app.api.deps import get_session
from app.core.config import Settings
from app.core.security import Clinician, User, require_role
from app.domain.clock import FakeClock
from app.main import create_app
from app.services.jwks import JwksCache, _b64u_uint, thumbprint_kid

load_dotenv()          # picks up PATIENT_TEST_DATABASE_URL from .env when running on the host

ISSUER, AUDIENCE = "nephro-auth", "nephro-api"


def make_settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = dict(
        patient_database_url=os.environ.get("PATIENT_TEST_DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x"),
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


class FakeDirectory:
    """Stands in for auth-svc /auth/me. Asserts it is never called while a database transaction is open:
    a slow auth-svc must not be able to hold the patient row lock (review fix, phase 2)."""

    def __init__(self) -> None:
        self.default: str | None = "Dr. Test"
        self.names: dict[uuid.UUID, str | None] = {}
        self.calls: list[tuple[uuid.UUID, str, str | None]] = []
        self.sessions: list[Any] = []                 # every AsyncSession the app opened

    async def name_for(self, user_id: uuid.UUID, authorization: str, request_id: str | None) -> str | None:
        in_tx = [s for s in self.sessions if s.in_transaction()]
        assert not in_tx, "clinician name lookup (an HTTP call) happened inside a database transaction"
        self.calls.append((user_id, authorization, request_id))
        return self.names[user_id] if user_id in self.names else self.default


@pytest.fixture
def directory() -> FakeDirectory:
    return FakeDirectory()


@pytest.fixture
def app(settings: Settings, clock: FakeClock, jwks: JwksCache, directory: FakeDirectory) -> FastAPI:
    app = create_app(settings, clock=clock, jwks=jwks, directory=directory)

    async def tracked_session(request: Request) -> AsyncIterator[Any]:
        async with request.app.state.sessionmaker() as session:
            directory.sessions.append(session)
            yield session

    app.dependency_overrides[get_session] = tracked_session
    # Phase 2 has no business routes yet: a probe route proves the auth dependencies.
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
# Database fixtures: real Postgres test database (nephro_patient_db_test on the shared container)
# =============================================================================================
import subprocess  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TABLES = ("audit_events, encounter_diagnoses, encounter_vitals, patient_conditions, medications, allergies, "
          "encounters, patients")


@pytest.fixture(scope="session")
def migrated_db() -> str:
    """Runs ``alembic upgrade head`` once per session against the TEST database and returns its URL."""
    url = os.environ.get("PATIENT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("PATIENT_TEST_DATABASE_URL not set")
    env = {**os.environ, "PATIENT_DATABASE_URL": url}
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, env=env, check=True,
                   capture_output=True)
    return url


@pytest.fixture
async def db_engine(migrated_db: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(migrated_db)
    async with engine.begin() as conn:      # TRUNCATE does not fire row triggers (tests only, LLD §9.3)
        await conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
        await conn.execute(text("ALTER SEQUENCE patient_mrn_seq RESTART WITH 101"))
    yield engine
    await engine.dispose()
