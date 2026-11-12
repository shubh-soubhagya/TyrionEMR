"""Settings (LLD §17). All values come from environment variables; defaults suit local development."""
from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

UPSTREAM_NAMES = ("auth", "patient", "lab", "ai")


def _split(value: object) -> object:
    if isinstance(value, str):
        return [p.strip() for p in value.split(",") if p.strip()]
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    service_name: str = "gateway"
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"

    # Empty URL = service not deployed: its prefixes answer 503 UPSTREAM_NOT_DEPLOYED.
    # PATIENT_SVC_URL defaults to empty (LLD); .env.example and docker-compose.yml set it.
    auth_svc_url: str = "http://auth-svc:8000"
    patient_svc_url: str = ""
    lab_svc_url: str = ""
    ai_svc_url: str = ""

    jwks_url: str = ""
    jwt_issuer: str = "nephro-auth"
    jwt_audience: str = "nephro-api"
    jwks_ttl_s: float = 300
    jwks_min_refetch_s: float = 30
    jwks_max_stale_s: float = 86400
    jwks_fetch_timeout_s: float = 2
    jwks_require_thumbprint_kid: bool = True

    cors_allowed_origins: Annotated[list[str], NoDecode] = ["http://localhost:4200"]
    cors_max_age_s: int = 600

    upstream_connect_timeout_s: float = 1.0
    upstream_default_timeout_s: float = 5.0
    insights_timeout_s: float = 10.0
    upstream_pool_timeout_s: float = 1.0
    upstream_max_connections: int = 100
    upstream_max_keepalive: int = 20

    max_body_bytes: int = 1_048_576
    max_auth_body_bytes: int = 16_384
    max_url_bytes: int = 24_576

    rate_limit_enabled: bool = True
    rl_ip_global_per_min: int = 1200
    rl_ip_global_burst: int = 200
    rl_auth_login_per_min: int = 10
    rl_auth_login_burst: int = 5
    rl_auth_refresh_per_min: int = 60
    rl_auth_refresh_burst: int = 20
    rl_user_default_per_min: int = 300
    rl_user_default_burst: int = 100
    rl_ai_generate_per_min: int = 10
    rl_ai_generate_burst: int = 3
    rl_ai_poll_per_min: int = 300
    rl_ai_poll_burst: int = 60
    rl_max_keys: int = 100_000

    trust_proxy_hops: int = 0
    health_probe_interval_s: float = 10
    ready_requires: Annotated[list[str], NoDecode] = ["auth"]
    # /metrics: off switch like auth-svc (D18). With METRICS_TOKEN set it needs a Bearer token.
    metrics_enabled: bool = True
    metrics_token: str = ""
    docs_enabled: bool = False
    hsts_enabled: bool = False
    uvicorn_workers: int = 1

    @field_validator("cors_allowed_origins", "ready_requires", mode="before")
    @classmethod
    def _csv(cls, v: object) -> object:
        return _split(v)

    @model_validator(mode="after")
    def _derive(self) -> Settings:
        if not self.jwks_url:
            self.jwks_url = self.auth_svc_url.rstrip("/") + "/.well-known/jwks.json"
        if any("*" in o for o in self.cors_allowed_origins):
            raise ValueError("CORS_ALLOWED_ORIGINS must list exact origins; '*' cannot be used with credentials")
        return self

    def upstream_urls(self) -> dict[str, str]:
        return {"auth": self.auth_svc_url, "patient": self.patient_svc_url,
                "lab": self.lab_svc_url, "ai": self.ai_svc_url}


@lru_cache
def get_settings() -> Settings:
    return Settings()
