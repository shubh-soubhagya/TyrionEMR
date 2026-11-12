"""Settings (LLD B2). All values come from environment variables; defaults suit local development."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    service_name: str = "ai-svc"
    app_env: Literal["dev", "test", "production"] = "dev"      # "dev" enables X-Mock-Scenario (mock provider only)
    log_level: str = "INFO"

    # --- database -------------------------------------------------------------------------------
    ai_database_url: str
    ai_test_database_url: str | None = None
    ai_db_pool_size: int = 5
    ai_db_max_overflow: int = 5
    db_pool_timeout_s: float = 5.0
    db_statement_timeout_ms: int = 3000
    db_lock_timeout_ms: int = 2000
    db_idle_in_transaction_timeout_ms: int = 10000
    db_wait_attempts: int = 30
    ai_db_sslmode: Literal["disable", "require", "verify-full"] = "disable"
    ai_db_sslrootcert: str | None = None
    run_migrations_on_start: bool = True
    uvicorn_workers: int = 1                                   # AI-ADR-9: the semaphore/cache/jobs are per process

    # --- upstreams ------------------------------------------------------------------------------
    patient_svc_url: str = "http://patient-svc:8000"
    lab_svc_url: str = "http://lab-svc:8000"
    upstream_connect_timeout_s: float = 1.0
    upstream_read_timeout_s: float = 3.0
    upstream_retries: int = 2                                  # GET only: connect errors and 502/503/504
    upstream_bulk_read_timeout_s: float = 8.0
    upstream_pool_size: int = 20                               # bulkhead per upstream (B14)

    # --- auth -----------------------------------------------------------------------------------
    jwks_url: str = "http://auth-svc:8000/.well-known/jwks.json"
    jwt_issuer: str = "nephro-auth"
    jwt_audience: str = "nephro-api"
    jwks_cache_ttl_s: float = 300.0
    jwks_min_refetch_s: float = 30.0                           # unknown-kid refetch floor (A7)
    jwks_max_stale_s: float = 3600.0
    jwks_fetch_timeout_s: float = 3.0
    max_body_bytes: int = 1_048_576

    clinic_tz: str = "Asia/Kolkata"                            # "today" for rules, as_of and the quota day

    # --- LLM (used from phase 7; Groq only for now) --------------------------------------------
    llm_provider: Literal["mock", "groq"] = "groq"
    llm_model: str = "openai/gpt-oss-20b"                      # same model as the Granthan llm-service
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_api_key_file: str = "/run/secrets/llm_api_key"
    llm_temperature: float = 0.2
    llm_max_output_tokens: int = 1400
    llm_connect_timeout_s: float = 3.0
    llm_timeout_s: float = 30.0
    llm_retries: int = 1
    llm_rate_limit_max_wait_s: float = 10.0
    llm_max_concurrency: int = 4
    llm_slot_wait_s: float = 20.0
    llm_breaker_failures: int = 5
    llm_breaker_cooldown_s: float = 60.0
    llm_tools_enabled: bool = True
    llm_max_tool_iterations: int = 4
    llm_max_calls_per_turn: int = 3
    llm_max_tool_calls: int = 8
    tool_timeout_s: float = 3.0
    tool_result_max_bytes: int = 8192
    llm_context_max_chars: int = 24000
    llm_job_deadline_s: float = 90.0
    llm_job_ttl_s: float = 120.0
    reaper_interval_s: float = 15.0
    heartbeat_interval_s: float = 10.0
    job_min_token_ttl_s: float = 30.0
    ai_daily_quota_per_user: int = 50
    prompt_version: str = "v1"
    llm_mock_scenario: str = "success"

    # --- insights (B2, B4) ----------------------------------------------------------------------
    insights_cache_ttl_s: float = 30.0
    insights_bulk_page: int = 200
    insights_max_pages: int = 50
    no_recent_labs_days: int = 180
    egfr_discordance_tolerance: float = 12.0
    no_stage_lt60_min_days: int = 90
    dashboard_abnormal_per_patient: int = 2
    dashboard_abnormal_total: int = 8
    dashboard_attention_limit: int = 20

    @field_validator("clinic_tz")
    @classmethod
    def _valid_tz(cls, v: str) -> str:
        try:
            ZoneInfo(v)                                         # fail at start-up, not at the first date calculation
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown time zone {v!r}") from exc
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # required fields come from the environment
