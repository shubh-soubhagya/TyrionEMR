"""Audit-integrity item 2: no silent fallback to the legacy auth_svc role."""
import logging
import os
import re
import subprocess
import sys

import pytest

from app.core import guard
from app.core.guard import ConfigurationError, enforce_production, production_problems
from app.db.migration_url import resolve_migration_url, runtime_role_problem, url_username
from app.main import build_state, create_app
from tests.conftest import ROOT, make_settings

GOOD = dict(environment="production", seed_demo_users=False, cookie_secure=True, enable_public_signup=False,
            cors_allowed_origins=["https://emr.example.org"], auth_db_sslmode="verify-full")


def url_as(user):
    return f"postgresql+asyncpg://{user}:s3cret@postgres:5432/nephro_auth_db"


@pytest.fixture(autouse=True)
def key_mode(monkeypatch):
    monkeypatch.setattr(guard, "_file_mode", lambda _p: 0o600)


# ----------------------------------------------------------------------------- production guard
@pytest.mark.parametrize("role", ["auth_migrator", "auth_svc"])
def test_production_refuses_a_runtime_url_that_uses_a_non_runtime_role(role):
    settings = make_settings(**GOOD, auth_database_url=url_as(role))
    with pytest.raises(ConfigurationError) as exc:
        enforce_production(settings)
    assert any("runtime must use the least-privilege role" in p and role in p for p in exc.value.problems)


def test_production_accepts_the_runtime_role():
    assert production_problems(make_settings(**GOOD, auth_database_url=url_as("auth_app"))) == []


def test_the_problem_text_never_contains_the_password():
    problem = runtime_role_problem(url_as("auth_migrator"))
    assert problem and "s3cret" not in problem


# ------------------------------------------------------------------------ development warning
@pytest.mark.parametrize("role, warns", [("auth_migrator", True), ("auth_svc", True), ("auth_app", False)])
async def test_development_only_warns(caplog, rsa_key, clock, role, warns):
    from app.services.keystore import KeyStore, SigningKey, thumbprint_kid
    settings = make_settings(environment="development", auth_database_url=url_as(role))
    app = create_app(settings, clock)
    pub = rsa_key.public_key()
    kid = thumbprint_kid(pub)
    caplog.set_level(logging.WARNING)
    build_state(app, settings, clock, KeyStore(SigningKey(kid, rsa_key), {kid: pub}))     # does not raise
    await app.state.engine.dispose()
    seen = [r for r in caplog.records if r.getMessage() == "config.runtime_role_not_least_privilege"]
    assert bool(seen) is warns
    assert not any("s3cret" in str(r.__dict__) for r in caplog.records)


# --------------------------------------------------------------------------------- env.py check
def test_migrations_need_the_migration_url():
    with pytest.raises(RuntimeError) as exc:
        resolve_migration_url({})
    assert "AUTH_MIGRATION_DATABASE_URL" in str(exc.value)


def test_migrations_do_not_fall_back_to_the_runtime_url():
    env = {"AUTH_DATABASE_URL": url_as("auth_app")}
    with pytest.raises(RuntimeError) as exc:
        resolve_migration_url(env)
    message = str(exc.value)
    assert "AUTH_MIGRATION_DATABASE_URL" in message and "runtime role" in message
    assert "s3cret" not in message                                       # the URL is never echoed


def test_an_empty_migration_url_counts_as_missing():
    with pytest.raises(RuntimeError):
        resolve_migration_url({"AUTH_MIGRATION_DATABASE_URL": "", "AUTH_DATABASE_URL": url_as("auth_app")})


def test_the_migration_url_wins_when_both_are_set():
    env = {"AUTH_MIGRATION_DATABASE_URL": url_as("auth_migrator"), "AUTH_DATABASE_URL": url_as("auth_app")}
    assert url_username(resolve_migration_url(env)) == "auth_migrator"


def test_username_parsing_handles_encoded_passwords():
    assert url_username("postgresql+asyncpg://auth_app:p%40ss%3Aw@host:5433/db") == "auth_app"
    assert url_username("not a url") is None


def test_the_real_alembic_refuses_to_run_with_only_the_runtime_url():
    """env.py is wired to the check: a process with only AUTH_DATABASE_URL fails before it connects."""
    env = {k: v for k, v in os.environ.items() if k != "AUTH_MIGRATION_DATABASE_URL"}
    env["AUTH_DATABASE_URL"] = "postgresql+asyncpg://auth_app:s3cret@localhost:1/x"
    proc = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode != 0
    assert "AUTH_MIGRATION_DATABASE_URL is not set" in proc.stderr + proc.stdout
    assert "s3cret" not in proc.stderr + proc.stdout


# ----------------------------------------------------------------------------------- compose
def test_compose_has_no_fallback_to_the_legacy_role():
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    assert "auth_svc" not in code and "AUTH_DB_PW" not in code
    for var in ("AUTH_APP_DB_USER", "AUTH_APP_DB_PW", "AUTH_MIGRATOR_DB_USER", "AUTH_MIGRATOR_DB_PW"):
        assert re.search(r"\$\{" + var + r":\?", code), f"{var} must be a required variable"
        assert not re.search(r"\$\{" + var + r":-", code), f"{var} must not have a default"
    # both services that connect to the database require them
    assert code.count("${AUTH_MIGRATOR_DB_USER:?") == 2 and code.count("${AUTH_APP_DB_USER:?") == 1
