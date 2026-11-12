"""Settings (LLD Â§21). All values come from environment variables; defaults suit local development."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    service_name: str = "lab-svc"
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"

    lab_database_url: str
    lab_db_pool_size: int = 5
    lab_db_max_overflow: int = 5
    db_pool_timeout_s: float = 5.0              # wait for a free connection before 503
    db_wait_attempts: int = 30
    # TLS to Postgres: disable | require | verify-full (same semantics as auth-svc)
    lab_db_sslmode: Literal["disable", "require", "verify-full"] = "disable"
    lab_db_sslrootcert: str | None = None
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

    internal_bulk_max_limit: int = 200          # /internal/labs/status page cap
    catalog_cache_ttl_s: float = 300.0          # catalog + ranges cache lifetime (LLD B2)
    summary_max_ids: int = 50                   # GET /labs/summary batch cap (HLD §5.6)
    # patient-svc internal read, used only when creating a report (HLD §9)
    patient_svc_url: str = "http://patient-svc:8000"
    upstream_connect_timeout_s: float = 1.0
    upstream_read_timeout_s: float = 3.0
    upstream_max_retries: int = 2
    max_body_bytes: int = 1_048_576             # request bodies above this are rejected with 413
    clinic_tz: str = "Asia/Kolkata"             # "today" for date-only rules (P-09)
    list_default_page_size: int = 50
    list_max_page_size: int = 200
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
