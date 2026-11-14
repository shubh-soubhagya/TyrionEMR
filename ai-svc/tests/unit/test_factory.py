"""Provider selection: Groq is the default, and without a key it falls back to the mock outside production."""
from __future__ import annotations

from app.llm.factory import build_provider
from app.llm.mock import MockProvider
from tests.conftest import make_settings


def test_groq_without_a_key_uses_the_mock_outside_production(tmp_path) -> None:
    s = make_settings(llm_provider="groq", llm_api_key=None, llm_api_key_file=str(tmp_path / "none"), app_env="dev")
    assert isinstance(build_provider(s), MockProvider)


def test_groq_with_a_key_uses_groq(tmp_path) -> None:
    from app.llm.groq import GroqProvider

    s = make_settings(llm_provider="groq", llm_api_key="k-test", llm_api_key_file=str(tmp_path / "none"), app_env="dev")
    assert isinstance(build_provider(s), GroqProvider)


def test_production_keeps_groq_even_without_a_key(tmp_path) -> None:
    from app.llm.groq import GroqProvider

    s = make_settings(llm_provider="groq", llm_api_key=None, llm_api_key_file=str(tmp_path / "none"), app_env="production")
    assert isinstance(build_provider(s), GroqProvider)


def test_mock_is_still_selectable() -> None:
    assert isinstance(build_provider(make_settings(llm_provider="mock")), MockProvider)
