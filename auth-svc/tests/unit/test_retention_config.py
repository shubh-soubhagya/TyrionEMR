"""Audit-integrity item 1: AUTH_EVENTS_RETENTION_DAYS must be at least 30."""
import os
import subprocess
import sys

import pytest
from pydantic import ValidationError

from app.core import guard
from app.core.guard import production_problems
from tests.conftest import ROOT, make_settings


@pytest.mark.parametrize("days", [0, 1, 10, 29])
def test_a_retention_below_30_is_refused_with_a_clear_message(days):
    with pytest.raises(ValidationError) as exc:
        make_settings(auth_events_retention_days=days)
    text = str(exc.value)
    assert "AUTH_EVENTS_RETENTION_DAYS must be at least 30" in text
    assert "database refuses" in text


@pytest.mark.parametrize("days", [30, 90, 365, 3650])
def test_30_days_and_more_are_accepted(days):
    assert make_settings(auth_events_retention_days=days).auth_events_retention_days == days


def test_the_production_guard_also_reports_it(monkeypatch):
    monkeypatch.setattr(guard, "_file_mode", lambda _p: 0o600)
    good = dict(environment="production", enable_public_signup=False, seed_demo_users=False, cookie_secure=True,
                cors_allowed_origins=["https://emr.example.org"], auth_db_sslmode="verify-full")
    settings = make_settings(**good)
    assert production_problems(settings) == []
    # model_copy skips validation: this is the guard's own check, independent of the field validator
    bad = settings.model_copy(update={"auth_events_retention_days": 10})
    assert any("AUTH_EVENTS_RETENTION_DAYS must be at least 30" in p for p in production_problems(bad))


def test_startup_fails_with_the_message_when_the_environment_sets_10():
    env = {**os.environ, "AUTH_EVENTS_RETENTION_DAYS": "10", "ENVIRONMENT": "development",
           "AUTH_DATABASE_URL": "postgresql+asyncpg://u:p@localhost:1/x", "JWT_PRIVATE_KEY_PATH": "nope.pem"}
    proc = subprocess.run([sys.executable, "-m", "uvicorn", "app.main:app", "--port", "8996"], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=60)
    output = proc.stdout + proc.stderr
    assert proc.returncode != 0
    assert "AUTH_EVENTS_RETENTION_DAYS must be at least 30" in output
