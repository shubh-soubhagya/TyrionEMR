"""Settings (LLD §21). All values come from environment variables; defaults suit local development."""
from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

MIN_AUDIT_RETENTION_DAYS = 30


def _split(value: object) -> object:
    if isinstance(value, str):
        return [p.strip() for p in value.split(",") if p.strip()]
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    service_name: str = "auth-svc"
    environment: Literal["development", "test", "production"] = "development"
    allow_public_signup_in_production: bool = False
    log_level: str = "INFO"

    auth_database_url: str                      # RUNTIME connection: the DML-only role auth_app
    # Used only by Alembic and the migrate job: the role that owns the schema (auth_migrator).
    # Unset = fall back to AUTH_DATABASE_URL (single-role setups, tests).
    auth_migration_database_url: str | None = None
    run_migrations_on_start: bool = False       # local convenience; production runs the migrate job
    auth_db_pool_size: int = 5
    auth_db_max_overflow: int = 5
    db_wait_attempts: int = 30
    # Server-side limits so a stuck query or lock turns into a fast 503, not a hung request (item 6)
    # TLS to Postgres: disable | require (encrypt; verifies the chain only if a root cert is given) | verify-full
    auth_db_sslmode: Literal["disable", "require", "verify-full"] = "disable"
    auth_db_sslrootcert: str | None = None
    db_statement_timeout_ms: int = 5000
    db_lock_timeout_ms: int = 2000
    db_idle_in_transaction_timeout_ms: int = 10000

    jwt_issuer: str = "nephro-auth"
    jwt_audience: str = "nephro-api"
    jwt_private_key_path: str = "/run/secrets/jwt_private"
    jwt_additional_public_key_paths: Annotated[list[str], NoDecode] = []

    access_token_ttl_min: int = 15
    refresh_token_ttl_days: int = 7
    session_max_days: int = 30
    refresh_reuse_grace_s: int = 10
    refresh_retention_days: int = 7
    auth_events_retention_days: int = 365      # audit rows older than this are purged by the cleanup job
    cleanup_interval_s: int = 3600

    refresh_cookie_name: str = "nephro_rt"
    refresh_cookie_path: str = "/api/auth"
    cookie_secure: bool = True
    cors_allowed_origins: Annotated[list[str], NoDecode] = ["http://localhost:4200"]

    enable_public_signup: bool = True
    login_max_attempts: int = 5
    login_lock_minutes: int = 15
    lockout_reveal: bool = True
    login_failure_window_minutes: int = 15      # failures older than this no longer count toward lockout

    # In-process per-IP token bucket (per worker process). The gateway is the real limiter.
    rate_limit_enabled: bool = True
    rate_limit_login_per_min: int = 10          # sustained refill rate
    rate_limit_login_burst: int = 5             # bucket size: requests allowed back-to-back

    argon2_time_cost: int = 3
    argon2_memory_kib: int = 65536
    argon2_parallelism: int = 4
    argon2_max_concurrency: int = 4
    argon2_queue_timeout_s: float = 2.0         # max wait for a hash slot before 503 SERVICE_BUSY

    # /metrics is for the internal network only (Prometheus). Turn it off if nothing scrapes it.
    metrics_enabled: bool = True

    seed_demo_users: bool = False
    uvicorn_workers: int = 2

    @field_validator("auth_events_retention_days")
    @classmethod
    def _retention_floor(cls, v: int) -> int:
        # The database function purge_auth_events refuses anything below 30 days, so a lower value would
        # make every cleanup run fail. Refuse to start instead, with a message that says why.
        if v < MIN_AUDIT_RETENTION_DAYS:
            raise ValueError(
                f"AUTH_EVENTS_RETENTION_DAYS must be at least {MIN_AUDIT_RETENTION_DAYS} "
                "(the database refuses to purge audit events newer than that)")
        return v

    @field_validator("jwt_additional_public_key_paths", "cors_allowed_origins", mode="before")
    @classmethod
    def _csv(cls, v: object) -> object:
        return _split(v)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # required fields come from the environment
