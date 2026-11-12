"""Groq adapter against respx fixtures of the OpenAI-compatible wire format (LLD B17.4). No network, no real key."""
from __future__ import annotations

import json
import logging

import httpx
import pytest
import respx

from app.llm.base import (
    LLMAuthError,
    LLMRateLimited,
    LLMRejected,
    LLMRequest,
    LLMTimeout,
    LLMUnavailable,
    Message,
    ToolCall,
    ToolDef,
)
from app.llm.factory import build_llm, build_provider, read_api_key
from app.llm.groq import GroqProvider, parse_retry_after, to_wire_messages
from tests.conftest import make_settings

URL = "https://api.groq.com/openai/v1/chat/completions"
KEY = "gsk_test_secret_key_123"
TOOLS = [ToolDef("get_lab_trend", "trend", {"type": "object", "properties": {"test_code": {"type": "string"}}})]


def req(**kw) -> LLMRequest:
    base = dict(system="SYSTEM", messages=[Message("user", "hello")], tools=None, json_mode=True, response_schema=None,
                temperature=0.2, max_output_tokens=2048, timeout_s=10)
    return LLMRequest(**(base | kw))


def ok_body(content='{"a":1}', tool_calls=None, finish="stop"):
    msg = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return {"choices": [{"message": msg, "finish_reason": finish}], "usage": {"prompt_tokens": 120, "completion_tokens": 30}}


@pytest.fixture
def provider():
    return GroqProvider(make_settings(llm_provider="groq", llm_model="openai/gpt-oss-20b"), KEY)


@pytest.fixture
def groq():
    with respx.mock(assert_all_called=False) as r:
        yield r


async def test_request_shape_for_a_final_json_turn(provider, groq):
    route = groq.post(URL).mock(return_value=httpx.Response(200, json=ok_body()))
    resp = await provider.generate(req())
    sent = route.calls.last.request
    body = json.loads(sent.content)
    assert sent.headers["authorization"] == f"Bearer {KEY}" and KEY not in str(sent.url)
    assert body["model"] == "openai/gpt-oss-20b" and body["temperature"] == 0.2
    assert body["max_completion_tokens"] == 2048 and body["reasoning_effort"] == "low"
    assert body["response_format"] == {"type": "json_object"} and "tools" not in body
    assert body["messages"][0] == {"role": "system", "content": "SYSTEM"}
    assert resp.text == '{"a":1}' and (resp.tokens_in, resp.tokens_out) == (120, 30) and resp.finish_reason == "stop"


async def test_tool_turns_send_tools_without_json_mode(provider, groq):
    route = groq.post(URL).mock(return_value=httpx.Response(200, json=ok_body()))
    await provider.generate(req(tools=TOOLS, json_mode=True))
    body = json.loads(route.calls.last.request.content)
    assert body["tools"][0]["function"]["name"] == "get_lab_trend" and body["tool_choice"] == "auto"
    assert "response_format" not in body                       # json_with_tools is false for Groq
    assert provider.capabilities.json_with_tools is False and provider.capabilities.supports_tools


async def test_tool_calls_are_parsed(provider, groq):
    calls = [{"id": "call_1", "type": "function", "function": {"name": "get_lab_trend",
                                                                  "arguments": '{"test_code": "EGFR"}'}},
             {"id": "call_2", "type": "function", "function": {"name": "get_gap_report", "arguments": ""}}]
    groq.post(URL).mock(return_value=httpx.Response(200, json=ok_body(None, calls, "tool_calls")))
    resp = await provider.generate(req(tools=TOOLS))
    assert resp.tool_calls == [ToolCall("call_1", "get_lab_trend", {"test_code": "EGFR"}),
                               ToolCall("call_2", "get_gap_report", {})]
    assert resp.text is None


def test_conversation_is_sent_in_openai_form():
    msgs = [Message("user", "u"), Message("assistant", None, (ToolCall("c1", "t", {"x": 1}),)),
            Message("tool", '{"r":1}', tool_call_id="c1", name="t"), Message("assistant", "a")]
    wire = to_wire_messages("S", msgs)
    assert [m["role"] for m in wire] == ["system", "user", "assistant", "tool", "assistant"]
    assert wire[2]["tool_calls"][0]["function"] == {"name": "t", "arguments": '{"x": 1}'}
    assert wire[3] == {"role": "tool", "tool_call_id": "c1", "content": '{"r":1}'}


@pytest.mark.parametrize(("status", "headers", "exc"), [
    (429, {"retry-after": "7"}, LLMRateLimited), (401, {}, LLMAuthError), (403, {}, LLMAuthError),
    (400, {}, LLMRejected), (422, {}, LLMRejected), (500, {}, LLMUnavailable), (503, {}, LLMUnavailable),
    (418, {}, LLMUnavailable)])
async def test_status_mapping(provider, groq, status, headers, exc):
    groq.post(URL).mock(return_value=httpx.Response(status, headers=headers, json={"error": {"message": "echoes prompt"}}))
    with pytest.raises(exc) as e:
        await provider.generate(req())
    if exc is LLMRateLimited:
        assert e.value.retry_after == 7


def test_retry_after_parsing():
    assert parse_retry_after("2") == 2.0 and parse_retry_after("1.5") == 1.5
    assert parse_retry_after("7m12s") is None and parse_retry_after(None) is None


async def test_timeouts_and_connection_errors(provider, groq):
    groq.post(URL).mock(side_effect=httpx.ReadTimeout("x"))
    with pytest.raises(LLMTimeout):
        await provider.generate(req())
    groq.post(URL).mock(side_effect=httpx.ConnectError("x"))
    with pytest.raises(LLMUnavailable):
        await provider.generate(req())


@pytest.mark.parametrize("body", [{}, {"choices": []}, {"choices": [{"message": None}]},
                                  {"choices": [{"message": {"tool_calls": [{"id": "x"}]}, "finish_reason": "stop"}]}])
async def test_malformed_provider_envelope_is_unavailable(provider, groq, body):
    groq.post(URL).mock(return_value=httpx.Response(200, json=body))
    with pytest.raises(LLMUnavailable):
        await provider.generate(req())


async def test_non_json_200_is_unavailable(provider, groq):
    groq.post(URL).mock(return_value=httpx.Response(200, text="<html>"))
    with pytest.raises(LLMUnavailable):
        await provider.generate(req())


async def test_truncated_reasoning_output_is_passed_on_for_validation(provider, groq):
    groq.post(URL).mock(return_value=httpx.Response(200, json=ok_body('{"history_summary": {"te', finish="length")))
    resp = await provider.generate(req())
    assert resp.finish_reason == "length" and resp.text.startswith('{"history')


async def test_missing_key_is_an_auth_error_without_a_request(groq):
    route = groq.post(URL).mock(return_value=httpx.Response(200, json=ok_body()))
    with pytest.raises(LLMAuthError):
        await GroqProvider(make_settings(), None).generate(req())
    assert route.call_count == 0


async def test_the_key_and_prompts_never_reach_the_logs(provider, groq, caplog):
    caplog.set_level(logging.DEBUG)
    groq.post(URL).mock(return_value=httpx.Response(401, json={"error": {"message": "bad key SYSTEM hello"}}))
    with pytest.raises(LLMAuthError):
        await provider.generate(req(messages=[Message("user", "PRIVATE-PATIENT-TEXT")]))
    logged = " ".join(r.getMessage() + str(r.__dict__) for r in caplog.records)
    assert KEY not in logged and "PRIVATE-PATIENT-TEXT" not in logged


def test_reasoning_effort_only_for_gpt_oss():
    other = GroqProvider(make_settings(llm_provider="groq", llm_model="llama-3.3-70b-versatile"), KEY)
    assert other._effort is None


# ---- factory and key handling ------------------------------------------------------------------
def test_factory_builds_mock_and_groq(tmp_path):
    mock = build_provider(make_settings(llm_provider="mock"))
    assert mock.name == "mock" and mock.model == "mock-1"
    g = build_provider(make_settings(llm_provider="groq", llm_api_key=KEY, llm_api_key_file=str(tmp_path / "none")))
    assert g.name == "groq" and g.model == "openai/gpt-oss-20b"
    llm = build_llm(make_settings(llm_provider="mock"))
    assert llm.name == "mock" and llm.cfg.max_concurrency == 4


def test_secret_file_wins_over_the_environment_key(tmp_path, monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    f = tmp_path / "llm_api_key"
    f.write_text("  from-file\n", encoding="utf-8")
    assert read_api_key(make_settings(llm_api_key="from-env", llm_api_key_file=str(f))) == "from-file"
    assert read_api_key(make_settings(llm_api_key="from-env", llm_api_key_file=str(tmp_path / "missing"))) == "from-env"
    missing = read_api_key(make_settings(llm_api_key_file=str(tmp_path / "missing"))) is None
    assert missing                                  # (compared without echoing a key into the test output)
