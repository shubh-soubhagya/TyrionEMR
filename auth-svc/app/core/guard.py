"""Production startup guard (fail fast on unsafe configuration)."""
from __future__ import annotations

import os
from collections.abc import Callable

from app.core.config import MIN_AUDIT_RETENTION_DAYS, Settings


class ConfigurationError(RuntimeError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def _file_mode(path: str) -> int | None:
    try:
        return os.stat(path).st_mode & 0o777
    except OSError:
        return None          # a missing key is reported by KeyStore with its own clear error


def production_problems(s: Settings, file_mode: Callable[[str], int | None] | None = None) -> list[str]:
    if s.environment != "production":
        return []
    file_mode = file_mode or _file_mode          # resolved at call time so tests can substitute it
    problems: list[str] = []
    if s.seed_demo_users:
        problems.append("SEED_DEMO_USERS must be false")
    if not s.cookie_secure:
        problems.append("COOKIE_SECURE must be true")
    if any("localhost" in o or o.strip() == "*" or "*" in o for o in s.cors_allowed_origins):
        problems.append("CORS_ALLOWED_ORIGINS must not contain localhost or *")
    mode = file_mode(s.jwt_private_key_path)
    if mode is not None and mode & 0o077:
        problems.append(f"JWT private key must not be group/world readable (mode is {mode:04o}, expected 0600)")
    if s.auth_db_sslmode == "disable":
        problems.append("AUTH_DB_SSLMODE must be require or verify-full (database traffic must be encrypted)")
    if s.auth_events_retention_days < MIN_AUDIT_RETENTION_DAYS:
        problems.append(f"AUTH_EVENTS_RETENTION_DAYS must be at least {MIN_AUDIT_RETENTION_DAYS}")
    if s.enable_public_signup and not s.allow_public_signup_in_production:
        problems.append("ENABLE_PUBLIC_SIGNUP=true needs ALLOW_PUBLIC_SIGNUP_IN_PRODUCTION=true")
    return problems


def enforce_production(s: Settings, file_mode: Callable[[str], int | None] | None = None) -> None:
    problems = production_problems(s, file_mode)
    if problems:
        raise ConfigurationError(problems)
