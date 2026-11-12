"""Groq adapter over raw httpx (AI-ADR-6, LLD B7.2). Groq's chat API is OpenAI-compatible.

* ``POST {base}/openai/v1/chat/completions`` with ``Authorization: Bearer`` (the key is never in a URL or a log).
* Tools use OpenAI-style ``tools``; JSON mode is ``response_format: {"type": "json_object"}``.
* ``json_with_tools`` is treated as FALSE: tool turns run without JSON mode and the orchestrator forces a final
  turn with no tools and JSON mode on (B7.3).
* The default model, ``openai/gpt-oss-20b``, is a reasoning model: reasoning tokens count against the completion
  limit, so ``reasoning_effort`` is kept low and ``finish_reason == "length"`` is surfaced to the validator as
  (probably truncated) text rather than hidden.
* Provider error bodies are never logged: they can echo the prompt.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx

from app.core.config import Settings
from app.llm.base import (
    Capabilities,
    LLMAuthError,
    LLMRateLimited,
    LLMRejected,
    LLMRequest,
    LLMResponse,
    LLMTimeout,
    LLMUnavailable,
    Message,
    ToolCall,
)

log = logging.getLogger("ai.llm.groq")
DEFAULT_BASE = "https://api.groq.com"
PATH = "/openai/v1/chat/completions"


def to_wire_messages(system: str, messages: list[Message]) -> list[dict[str, Any]]:
    wire: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for m in messages:
        if m.role == "assistant":
            item: dict[str, Any] = {"role": "assistant", "content": m.content or ""}
            if m.tool_calls:
                item["tool_calls"] = [{"id": c.id, "type": "function",
                                       "function": {"name": c.name, "arguments": json.dumps(c.arguments)}}
                                      for c in m.tool_calls]
            wire.append(item)
        elif m.role == "tool":
            wire.append({"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content or ""})
        else:
            wire.append({"role": "user", "content": m.content or ""})
    return wire


def parse_retry_after(value: str | None) -> float | None:
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None                       # an HTTP-date or "7m12s" style value: treated as 'too long to wait'


class GroqProvider:
    name = "groq"
    capabilities = Capabilities(supports_tools=True, supports_json_mode=True, json_with_tools=False,
                                supports_response_schema=False, max_context_chars=400_000)

    def __init__(self, settings: Settings, api_key: str | None, transport: httpx.AsyncBaseTransport | None = None,
                 reasoning_effort: str | None = "low") -> None:
        self.model = settings.llm_model
        self._key = api_key
        self._effort = reasoning_effort if "gpt-oss" in settings.llm_model else None
        self._http = httpx.AsyncClient(base_url=settings.llm_base_url or DEFAULT_BASE, transport=transport,
                                       timeout=httpx.Timeout(settings.llm_timeout_s,
                                                             connect=settings.llm_connect_timeout_s))

    async def aclose(self) -> None:
        await self._http.aclose()

    def _body(self, req: LLMRequest) -> dict[str, Any]:
        body: dict[str, Any] = {"model": self.model, "messages": to_wire_messages(req.system, req.messages),
                                "temperature": req.temperature, "max_completion_tokens": req.max_output_tokens}
        if req.tools:
            body["tools"] = [{"type": "function", "function": {"name": t.name, "description": t.description,
                                                                "parameters": t.parameters}} for t in req.tools]
            body["tool_choice"] = "auto"
        if req.json_mode and not req.tools:                     # json_with_tools is false for Groq
            body["response_format"] = {"type": "json_object"}
        if self._effort:
            body["reasoning_effort"] = self._effort
        return body

    async def generate(self, req: LLMRequest) -> LLMResponse:
        if not self._key:
            log.error("llm.no_api_key")
            raise LLMAuthError("no API key configured")
        started = time.monotonic()
        try:
            r = await self._http.post(PATH, json=self._body(req), headers={"Authorization": f"Bearer {self._key}"},
                                      timeout=httpx.Timeout(req.timeout_s, connect=min(3.0, req.timeout_s)))
        except httpx.TimeoutException:
            raise LLMTimeout("groq timeout") from None
        except httpx.HTTPError:
            raise LLMUnavailable("groq connection error") from None
        status = r.status_code
        if status == 429:
            raise LLMRateLimited(parse_retry_after(r.headers.get("retry-after")))
        if status in (401, 403):
            log.error("llm.auth_rejected", extra={"http_status": status})
            raise LLMAuthError("groq rejected the API key")
        if status in (400, 404, 413, 422):
            log.error("llm.request_rejected", extra={"http_status": status})   # our request is wrong: a bug
            raise LLMRejected(f"groq rejected the request ({status})")
        if status >= 500 or status != 200:
            raise LLMUnavailable(f"groq status {status}")
        return self._parse(r, started)

    @staticmethod
    def _parse(r: httpx.Response, started: float) -> LLMResponse:
        try:
            data = r.json()
            choice = data["choices"][0]
            msg = choice["message"]
            calls = [ToolCall(c["id"], c["function"]["name"], json.loads(c["function"].get("arguments") or "{}"))
                     for c in msg.get("tool_calls") or []]
            usage = data.get("usage") or {}
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            raise LLMUnavailable("malformed groq response") from None       # malformed provider envelope
        return LLMResponse(text=msg.get("content"), tool_calls=calls, finish_reason=str(choice.get("finish_reason")),
                           tokens_in=usage.get("prompt_tokens"), tokens_out=usage.get("completion_tokens"),
                           latency_ms=round((time.monotonic() - started) * 1000))
