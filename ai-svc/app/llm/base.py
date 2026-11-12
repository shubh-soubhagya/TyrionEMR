"""Provider-neutral LLM types (LLD B7.1). Adapters raise only the exceptions below; the orchestrator maps each to an
error code. The llm package knows nothing about patients, repositories or clients (A5)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


@dataclass(frozen=True)
class Capabilities:
    supports_tools: bool
    supports_json_mode: bool
    json_with_tools: bool                  # JSON mode and tools allowed in the same request
    supports_response_schema: bool
    max_context_chars: int


@dataclass(frozen=True)
class ToolDef:
    """A tool as the model sees it: name, description and a JSON Schema for the arguments."""
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class Message:
    role: Literal["user", "assistant", "tool"]
    content: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()          # assistant turns that asked for tools
    tool_call_id: str | None = None                # tool turns answer one call
    name: str | None = None


@dataclass(frozen=True)
class LLMRequest:
    system: str
    messages: list[Message]
    tools: list[ToolDef] | None
    json_mode: bool
    response_schema: dict[str, Any] | None
    temperature: float
    max_output_tokens: int
    timeout_s: float
    extra: dict[str, Any] = field(default_factory=dict)      # provider hints, for example the mock scenario


@dataclass(frozen=True)
class LLMResponse:
    text: str | None
    tool_calls: list[ToolCall]
    finish_reason: str
    tokens_in: int | None
    tokens_out: int | None
    latency_ms: int


class LLMProvider(Protocol):
    name: str
    model: str
    capabilities: Capabilities

    async def generate(self, req: LLMRequest) -> LLMResponse: ...


class LLMError(Exception):
    code = "INTERNAL_ERROR"


class LLMTimeout(LLMError):
    code = "LLM_TIMEOUT"


class LLMUnavailable(LLMError):
    code = "LLM_UNAVAILABLE"


class LLMRateLimited(LLMError):
    code = "LLM_RATE_LIMITED"

    def __init__(self, retry_after: float | None = None) -> None:
        super().__init__("rate limited")
        self.retry_after = retry_after


class LLMRejected(LLMError):
    """400 for our own request (bad schema or tool definition): a bug, logged at ERROR."""
    code = "INTERNAL_ERROR"


class LLMAuthError(LLMError):
    """401/403 from the provider (bad or missing key): logged at ERROR, shown as 'unavailable'."""
    code = "LLM_UNAVAILABLE"


class LLMCircuitOpen(LLMError):
    code = "LLM_CIRCUIT_OPEN"


class LLMBusy(LLMError):
    code = "LLM_BUSY"
