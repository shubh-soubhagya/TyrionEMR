"""Settings (LLD Â§21). All values come from environment variables; defaults suit local development."""
from __future__ import annotations

from datetime import date
from functools import lru_cache
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.domain.trends import TrendConfig


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
    db_statement_timeout_ms: int = 5000
    db_lock_timeout_ms: int = 2000
    db_idle_in_transaction_timeout_ms: int = 10000

    jwks_url: str = "http://auth-svc:8000/.well-known/jwks.json"
    jwks_cache_ttl_s: float = 300.0
    jwks_min_refetch_s: float = 10.0            # floor between unknown-kid refetches (no hammering auth-svc)
    jwks_max_stale_s: float = 3600.0            # keys older than this are no longer trusted
    jwks_fetch_timeout_s: float = 3.0
    jwt_issuer: str = "nephro-auth"
    jwt_audience: str = "nephro-api"

    # request limits (LLD B2)
    summary_max_ids: int = 50                   # GET /labs/summary
    results_page_max: int = 100                 # max `size` for result pages
    status_bulk_max: int = 200                  # max `limit` for /internal/labs/status
    catalog_cache_ttl_s: float = 300.0          # catalog + ranges cache lifetime
    clock_skew_s: int = 60                      # tolerance when rejecting a future collected_at
    # rules (changing any of these changes RULES_VERSION, see domain/constants.py)
    spark_points: int = 12                      # eGFR points kept in the read model
    trend_min_points: int = 3                   # below this, direction = insufficient_data
    egfr_stable_band: float = 2.0               # mL/min/1.73 m2 per year
    creat_stable_band: float = 0.1              # mg/dL per year
    egfr_rapid_decline: float = -5.0            # slope at or below this is rapid decline
    # synthetic data (development only)
    seed_anchor_date: date | None = None        # day the demo data counts back from; default today
    seed_allow_reset: bool = False              # must be true for `seed_labs --reset`
    # patient-svc: read only, and only when creating a report (HLD section 9)
    patient_svc_url: str = "http://patient-svc:8000"
    patient_connect_timeout_s: float = 1.0
    patient_read_timeout_s: float = 3.0
    patient_retries: int = 2                    # GET only, connect errors and 502/503/504
    patient_pool_size: int = 10                 # bulkhead
    max_body_bytes: int = 1_048_576             # request bodies above this are rejected with 413
    clinic_tz: str = "Asia/Kolkata"             # "today" for date-only rules (P-09)
    uvicorn_workers: int = 2

    def trend_config(self) -> TrendConfig:
        return TrendConfig(min_points=self.trend_min_points, egfr_stable_band=self.egfr_stable_band,
                           creat_stable_band=self.creat_stable_band, egfr_rapid_decline=self.egfr_rapid_decline)

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
