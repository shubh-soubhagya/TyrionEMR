"""Production startup guard (deviation D3): refuse to start on an unsafe configuration.

Same pattern as auth-svc/app/core/guard.py. Only ENVIRONMENT=production is checked.
"""
from __future__ import annotations

from app.core.config import Settings


class ConfigurationError(RuntimeError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def production_problems(s: Settings) -> list[str]:
    if s.environment != "production":
        return []
    problems: list[str] = []
    if any("localhost" in o or "*" in o for o in s.cors_allowed_origins):
        problems.append("CORS_ALLOWED_ORIGINS must not contain localhost or *")
    if s.docs_enabled:
        problems.append("DOCS_ENABLED must be false")
    if s.metrics_enabled and not s.metrics_token:
        problems.append("METRICS_ENABLED=true needs a non-empty METRICS_TOKEN")
    if not s.rate_limit_enabled:
        problems.append("RATE_LIMIT_ENABLED must be true")
    if not s.hsts_enabled:
        problems.append("HSTS_ENABLED must be true (production runs behind TLS)")
    return problems


def enforce_production(s: Settings) -> None:
    problems = production_problems(s)
    if problems:
        raise ConfigurationError(problems)
