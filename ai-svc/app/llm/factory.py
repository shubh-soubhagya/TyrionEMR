"""Builds the provider from settings (LLD B7.2). Groq is the real provider for now; the others are not built."""
from __future__ import annotations

import os
from pathlib import Path

from app.core.config import Settings
from app.llm.base import LLMProvider
from app.llm.mock import MockProvider
from app.llm.resilience import ResilienceConfig, ResilientLLM


def read_api_key(s: Settings) -> str | None:
    """Docker secret file first, then LLM_API_KEY (host runs). Never logged."""
    path = Path(s.llm_api_key_file)
    if path.is_file():
        key = path.read_text(encoding="utf-8").strip()
        if key:
            return key
    return s.llm_api_key or os.environ.get("LLM_API_KEY") or None


def build_provider(s: Settings) -> LLMProvider:
    if s.llm_provider == "mock":
        return MockProvider(s.llm_model if s.llm_model != "openai/gpt-oss-20b" else "mock-1", s.llm_mock_scenario)
    if s.llm_provider == "groq":
        from app.llm.groq import GroqProvider  # imported lazily: the mock must run without an API key
        return GroqProvider(s, read_api_key(s))
    raise ValueError(f"unsupported LLM_PROVIDER {s.llm_provider!r}")


def build_llm(s: Settings, provider: LLMProvider | None = None) -> ResilientLLM:
    cfg = ResilienceConfig(retries=s.llm_retries, rate_limit_max_wait_s=s.llm_rate_limit_max_wait_s,
                           max_concurrency=s.llm_max_concurrency, slot_wait_s=s.llm_slot_wait_s,
                           breaker_failures=s.llm_breaker_failures, breaker_cooldown_s=s.llm_breaker_cooldown_s,
                           http_timeout_s=s.llm_timeout_s)
    return ResilientLLM(provider or build_provider(s), cfg)
