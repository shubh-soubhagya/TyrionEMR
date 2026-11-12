"""Tool registry (LLD B8.2): validate, execute with a timeout, shape, cap, and record every call.

Tool calls are recorded in ``llm_tool_calls`` (arguments and result *sizes*, never results). A tool failure is fed back
to the model once as a tool result; it never fails the job.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.errors import PatientNotFound, UpstreamTimeout, UpstreamUnavailable
from app.core.metrics import LLM_TOOL_CALLS
from app.llm.base import ToolCall, ToolDef
from app.repositories import tool_calls as repo
from app.tools.definitions import SPECS, Deps, ToolSpec

log = logging.getLogger("ai.tools")


@dataclass
class ToolResult:
    data: dict[str, Any]
    ok: bool = True

    @classmethod
    def error(cls, message: str) -> ToolResult:
        return cls({"error": message}, ok=False)

    def to_message(self) -> str:
        return json.dumps(self.data, ensure_ascii=False, separators=(",", ":"), default=str)


def _code(exc: BaseException) -> str:
    if isinstance(exc, TimeoutError | UpstreamTimeout):
        return "TOOL_TIMEOUT"
    if isinstance(exc, PatientNotFound):
        return "PATIENT_NOT_FOUND"
    return "UPSTREAM_UNAVAILABLE"


def _short(exc: ValidationError) -> str:
    return "; ".join(f"{'.'.join(map(str, e['loc'])) or 'arguments'}: {e['msg']}"[:80] for e in exc.errors()[:3])


class ToolRegistry:
    def __init__(self, settings: Settings, sessionmaker: async_sessionmaker[AsyncSession], deps: Deps) -> None:
        self._cfg, self._sm, self._deps = settings, sessionmaker, deps
        self._specs: dict[str, ToolSpec] = {s.name: s for s in SPECS}

    def definitions(self) -> list[ToolDef]:
        return [ToolDef(s.name, s.description, s.parameters()) for s in self._specs.values()]

    async def execute(self, call: ToolCall, job: Any, iteration: int) -> ToolResult:
        if job.tool_calls >= self._cfg.llm_max_tool_calls:
            return await self._record(job, iteration, call.name, {"_name": call.name[:64]}, "rejected", "BUDGET_SPENT",
                                      ToolResult.error("Tool budget for this summary is used up."), 0)
        spec = self._specs.get(call.name)
        if spec is None:
            return await self._record(job, iteration, "unknown", {"_name": call.name[:64]}, "rejected", "UNKNOWN_TOOL",
                                      ToolResult.error("Unknown tool. Available: " + ", ".join(self._specs)), 0)
        try:
            args = spec.args_model.model_validate(call.arguments)                  # strict: extra = forbid
        except ValidationError as e:
            return await self._record(job, iteration, spec.name, _safe_args(call.arguments), "rejected",
                                      "INVALID_ARGUMENTS", ToolResult.error(_short(e)), 0)
        started = time.monotonic()
        try:
            async with asyncio.timeout(self._cfg.tool_timeout_s):
                raw = await spec.run(args, job, self._deps)
            data = spec.shape(raw, job, args, self._cfg.tool_result_max_bytes)
            result, status, error = ToolResult(data), "ok", None
        except (UpstreamUnavailable, UpstreamTimeout, PatientNotFound, TimeoutError) as e:
            result, status, error = ToolResult.error("Data could not be retrieved."), "error", _code(e)
        ms = round((time.monotonic() - started) * 1000)
        return await self._record(job, iteration, spec.name, args.model_dump(mode="json", by_alias=True), status,
                                  error, result, ms)

    async def _record(self, job: Any, iteration: int, name: str, arguments: dict[str, Any], status: str,
                      error: str | None, result: ToolResult, ms: int) -> ToolResult:
        job.tool_calls += 1
        body = result.to_message()
        rows = next((len(v) for k, v in result.data.items() if isinstance(v, list)), None) if result.ok else None
        truncated = bool(result.data.get("truncated")) if result.ok else False
        LLM_TOOL_CALLS.labels(name if name in self._specs else "unknown", status).inc()
        job.tool_results.append({"seq": job.tool_calls, "tool": name, "args": arguments, "rows": rows,
                                 "truncated": truncated})
        try:
            async with self._sm() as s, s.begin():
                await repo.append(s, summary_id=job.summary_id, seq=job.tool_calls, iteration=iteration,
                                  tool_name=name, arguments=arguments, status=status, latency_ms=ms,
                                  error_code=error, result_rows=rows, result_bytes=len(body.encode()),
                                  truncated=truncated)
        except Exception as exc:        # the trigger rejects rows for finished jobs; the audit row is best-effort
            log.warning("tool_call.record_failed", extra={"error_type": type(exc).__name__})
        return result


def _safe_args(arguments: Any) -> dict[str, Any]:
    """Arguments of a rejected call, bounded so a hostile model cannot bloat the audit row (CHECK <= 4 KB)."""
    try:
        text = json.dumps(arguments, default=str)
    except (TypeError, ValueError):
        return {}
    return {"_raw": text[:500]}
