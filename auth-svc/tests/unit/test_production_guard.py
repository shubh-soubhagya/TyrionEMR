"""Item 3: refuse to start on an unsafe production configuration."""
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from app.core import guard
from app.core.guard import ConfigurationError, enforce_production, production_problems
from app.main import build_state, create_app
from tests.conftest import make_settings

ROOT = Path(__file__).resolve().parents[2]
GOOD = dict(environment="production", seed_demo_users=False, cookie_secure=True, enable_public_signup=False,
            cors_allowed_origins=["https://emr.example.org"])


def mode_600(_path):
    return 0o600


def prod(**over):
    return make_settings(**{**GOOD, **over})


def test_a_valid_production_config_passes():
    assert production_problems(prod(), mode_600) == []
    enforce_production(prod(), mode_600)


@pytest.mark.parametrize("override, fragment", [
    ({"seed_demo_users": True}, "SEED_DEMO_USERS"),
    ({"cookie_secure": False}, "COOKIE_SECURE"),
    ({"cors_allowed_origins": ["http://localhost:4200"]}, "CORS_ALLOWED_ORIGINS"),
    ({"cors_allowed_origins": ["*"]}, "CORS_ALLOWED_ORIGINS"),
    ({"cors_allowed_origins": ["https://emr.example.org", "http://localhost:4200"]}, "CORS_ALLOWED_ORIGINS"),
    ({"enable_public_signup": True}, "ENABLE_PUBLIC_SIGNUP"),
])
def test_each_forbidden_setting_fails_startup(override, fragment):
    with pytest.raises(ConfigurationError) as exc:
        enforce_production(prod(**override), mode_600)
    assert any(fragment in p for p in exc.value.problems)


def test_public_signup_is_allowed_with_the_explicit_opt_in():
    enforce_production(prod(enable_public_signup=True, allow_public_signup_in_production=True), mode_600)


@pytest.mark.parametrize("mode", [0o640, 0o644, 0o660, 0o604, 0o777])
def test_group_or_world_readable_key_fails(mode):
    with pytest.raises(ConfigurationError) as exc:
        enforce_production(prod(), lambda _p: mode)
    assert any("private key" in p for p in exc.value.problems)


@pytest.mark.parametrize("mode", [0o600, 0o400])
def test_owner_only_key_is_fine(mode):
    enforce_production(prod(), lambda _p: mode)


def test_all_problems_are_reported_together():
    with pytest.raises(ConfigurationError) as exc:
        enforce_production(prod(seed_demo_users=True, cookie_secure=False), mode_600)
    assert len(exc.value.problems) == 2


def test_guard_does_nothing_outside_production():
    for env in ("development", "test"):
        enforce_production(make_settings(environment=env, seed_demo_users=True, cookie_secure=False))


def test_build_state_refuses_before_touching_anything():
    app = create_app(prod(seed_demo_users=True))
    with pytest.raises(ConfigurationError):
        build_state(app, prod(seed_demo_users=True), lambda: None)   # clock unused: it fails first
    assert not hasattr(app.state, "engine")


async def test_lifespan_fails_and_logs_the_reasons(capsys, monkeypatch):
    monkeypatch.setattr(guard, "_file_mode", mode_600)
    s = prod(seed_demo_users=True)
    app = create_app(s)
    with pytest.raises(ConfigurationError):
        async with app.router.lifespan_context(app):
            pass
    line = next(json.loads(ln) for ln in capsys.readouterr().out.splitlines() if "startup.refused" in ln)
    assert line["level"] == "CRITICAL" and any("SEED_DEMO_USERS" in p for p in line["problems"])


def test_process_exits_non_zero_when_started_unsafely():
    env = {**os.environ, "ENVIRONMENT": "production", "SEED_DEMO_USERS": "true", "COOKIE_SECURE": "false",
           "AUTH_DATABASE_URL": "postgresql+asyncpg://u:p@localhost:1/x", "JWT_PRIVATE_KEY_PATH": "nope.pem"}
    proc = subprocess.run([sys.executable, "-m", "uvicorn", "app.main:app", "--port", "8997"], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode != 0
    assert "startup.refused" in proc.stdout + proc.stderr
    assert "SEED_DEMO_USERS" in proc.stdout + proc.stderr


async def test_production_serves_no_docs_or_schema(monkeypatch, rsa_key, clock):
    from app.services.keystore import KeyStore, SigningKey, thumbprint_kid
    monkeypatch.setattr(guard, "_file_mode", mode_600)
    s = prod()
    app = create_app(s, clock)
    pub = rsa_key.public_key()
    kid = thumbprint_kid(pub)
    build_state(app, s, clock, KeyStore(SigningKey(kid, rsa_key), {kid: pub}))
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://auth.test") as c:
            for path in ("/docs", "/redoc", "/openapi.json"):
                r = await c.get(path)
                assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND", path
            assert (await c.get("/health")).status_code == 200
    finally:
        await app.state.engine.dispose()


async def test_development_still_serves_docs(client):
    assert (await client.get("/openapi.json")).status_code == 200


async def test_seed_users_refuses_in_production_even_with_force(monkeypatch, capsys):
    from app.cli import seed_users
    from app.core.config import get_settings
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("AUTH_DATABASE_URL", "postgresql+asyncpg://u:p@localhost:1/x")
    get_settings.cache_clear()
    try:
        assert await seed_users.main(force=True) == 1
    finally:
        get_settings.cache_clear()
    assert "Refusing" in capsys.readouterr().err
