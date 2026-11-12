"""Settings (LLD §21). All values come from environment variables; defaults suit local development."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    service_name: str = "patient-svc"
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"

    patient_database_url: str
    patient_db_pool_size: int = 5
    patient_db_max_overflow: int = 5
    db_pool_timeout_s: float = 5.0              # wait for a free connection before 503
    db_wait_attempts: int = 30
    # TLS to Postgres: disable | require | verify-full (same semantics as auth-svc)
    patient_db_sslmode: Literal["disable", "require", "verify-full"] = "disable"
    patient_db_sslrootcert: str | None = None
    db_statement_timeout_ms: int = 3000
    db_lock_timeout_ms: int = 2000
    db_idle_in_transaction_timeout_ms: int = 10000

    jwks_url: str = "http://auth-svc:8000/.well-known/jwks.json"
    jwks_cache_ttl_s: float = 300.0
    jwks_min_refetch_s: float = 10.0            # floor between unknown-kid refetches (no hammering auth-svc)
    jwks_max_stale_s: float = 3600.0            # keys older than this are no longer trusted
    jwks_fetch_timeout_s: float = 3.0
    jwt_issuer: str = "nephro-auth"
    jwt_audience: str = "nephro-api"

    internal_bulk_max_limit: int = 200          # /internal/patients/charts page cap
    internal_note_max_chars: int = 1500         # tool endpoint note truncation
    # Clinician display names come from auth-svc /auth/me with the caller's own token (tokens carry no PII)
    auth_me_url: str = "http://auth-svc:8000/auth/me"
    clinician_name_cache_ttl_s: float = 600.0
    clinician_name_negative_ttl_s: float = 30.0   # failed lookups: do not hammer auth-svc during an outage
    clinician_name_cache_max: int = 1000
    clinic_tz: str = "Asia/Kolkata"             # "today" for date-only rules (P-09)
    list_default_page_size: int = 20
    list_max_page_size: int = 100
    uvicorn_workers: int = 2

    @field_validator("clinic_tz")
    @classmethod
    def _valid_tz(cls, v: str) -> str:
        try:
            ZoneInfo(v)                          # fail at start-up, not at the first date calculation
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown time zone {v!r}") from exc
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # required fields come from the environment
