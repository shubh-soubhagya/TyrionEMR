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
        environment="test",
        rate_limit_enabled=False,      # dedicated tests turn it on; lockout tests send many logins from one IP
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


# =============================================================================================
# API fixtures: real Postgres test database (nephro_auth_db_test), fake clock, cheap argon2
# =============================================================================================
import subprocess  # noqa: E402
import sys  # noqa: E402
import uuid  # noqa: E402
from collections.abc import AsyncIterator, Callable  # noqa: E402
from http.cookies import SimpleCookie  # noqa: E402
from pathlib import Path  # noqa: E402

import httpx  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.main import build_state, create_app  # noqa: E402
from app.models import User  # noqa: E402
from app.services.keystore import KeyStore, SigningKey, thumbprint_kid  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
TEST_DB_URL = os.environ.get("AUTH_TEST_DATABASE_URL")
GOOD_PASSWORD = "Kidney2026care"


@pytest.fixture(scope="session")
def migrated_db() -> str:
    if not TEST_DB_URL:
        pytest.skip("AUTH_TEST_DATABASE_URL is not set")
    env = {**os.environ, "AUTH_DATABASE_URL": TEST_DB_URL}
    for cmd in (["downgrade", "base"], ["upgrade", "head"]):   # fresh schema from the real migration
        subprocess.run([sys.executable, "-m", "alembic", *cmd], cwd=ROOT, env=env, check=True,
                       capture_output=True)
    return TEST_DB_URL


@pytest.fixture
async def make_app(migrated_db, rsa_key, clock):
    """Factory: build an app against the test DB with per-test settings overrides."""
    created = []

    async def factory(keystore=None, truncate=True, **overrides):
        s = make_settings(auth_database_url=migrated_db, **overrides)
        pub = rsa_key.public_key()
        kid = thumbprint_kid(pub)
        app = create_app(s, clock)
        build_state(app, s, clock, keystore or KeyStore(SigningKey(kid, rsa_key), {kid: pub}))
        if truncate:
            async with app.state.engine.begin() as conn:
                await conn.execute(text("TRUNCATE users, auth_events CASCADE"))
        created.append(app)
        return app

    yield factory
    for a in created:
        await a.state.engine.dispose()


def client_for(app) -> httpx.AsyncClient:
    # raise_app_exceptions=False: unexpected errors surface as 500 envelopes, like in production
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                             base_url="https://auth.test")


@pytest.fixture
async def app(make_app):
    return await make_app()


@pytest.fixture
async def client(app) -> AsyncIterator[httpx.AsyncClient]:
    async with client_for(app) as c:
        yield c


@pytest.fixture
def make_user(app) -> Callable[..., object]:
    async def _make(email="dr.rao@nephrocare.demo", password=GOOD_PASSWORD, name="Dr. Anita Rao",
                    active=True) -> User:
        user = User(id=uuid.uuid4(), email=email, full_name=name, role="clinician", is_active=active,
                    password_hash=await app.state.hasher.hash(password),
                    created_at=app.state.clock(), updated_at=app.state.clock())
        async with app.state.sessionmaker() as s, s.begin():
            s.add(user)
        return user
    return _make


def rt_cookie(resp: httpx.Response) -> str | None:
    """The refresh token set by a response, or None if the response did not set/clear it."""
    for header in resp.headers.get_list("set-cookie"):
        c = SimpleCookie()
        c.load(header)
        if "nephro_rt" in c:
            return c["nephro_rt"].value or None
    return None


def set_cookie_headers(resp: httpx.Response) -> list[str]:
    return [h for h in resp.headers.get_list("set-cookie") if h.startswith("nephro_rt=")]


def with_cookie(raw: str) -> dict[str, str]:
    return {"cookie": f"nephro_rt={raw}"}


async def sql(app, query: str, **params):
    async with app.state.sessionmaker() as s:
        return (await s.execute(text(query), params)).all()
