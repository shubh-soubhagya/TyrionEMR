"""SummaryOrchestrator (LLD B10.4): the seven visible steps of one summary job.

    1 open_chart  2 gather  3 rules  4 prepare  5 write  6 check  7 save

Every outcome is persisted through the repositories: ``completed`` (validated AI content, or a cache hit),
``degraded`` (facts and rule findings saved, AI unavailable or invalid) or ``failed`` (the chart could not be
built). Nothing unvalidated is ever stored (B9). The job is cancellation-safe and heartbeat-driven (B10.5-B10.7).
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.clients.lab import LabClient
from app.clients.models import Chart, Latest, Trends
from app.clients.patient import PatientClient
from app.context.hashing import HashInputs, context_hash
from app.context.minimize import trim_to_budget
from app.context.packet import PACKET_VERSION, build_packet
from app.context.refs import RefBuilder
from app.core.clock import Clock
from app.core.config import Settings
from app.core.context import CallContext
from app.core.errors import PatientNotFound, UpstreamTimeout, UpstreamUnavailable
from app.core.metrics import AI_SUMMARIES, AI_SUMMARY_DURATION, AI_VALIDATION, LLM_TOKENS
from app.insights.rules.adapters import from_chart
from app.insights.rules.constants import RULES_VERSION
from app.insights.rules.facts import RuleConfig
from app.insights.rules.gaps import evaluate
from app.insights.service import gather_all
from app.llm.base import (
    LLMBusy,
    LLMCircuitOpen,
    LLMError,
    LLMRequest,
    LLMResponse,
    Message,
    ToolCall,
)
from app.llm.resilience import ResilientLLM
from app.orchestrator.facts import build_facts, build_gaps
from app.orchestrator.progress import JobGone, ProgressTracker
from app.prompts.loader import PromptSet
from app.repositories import summaries as repo
from app.schemas.jsonb import STEP_LABELS, ValidationBlock
from app.validation.hydrate import hydrate_sources, refs_in_blocks, refs_in_output
from app.validation.numbers import allowed_numbers
from app.validation.output_schema import SCHEMA_VERSION
from app.validation.pipeline import Verdict, parse_lenient, validate

log = logging.getLogger("ai.orchestrator")
SessionMaker = async_sessionmaker[AsyncSession]
STEP_KEYS = [k for k, _ in STEP_LABELS]


@dataclass
class JobContext:
    summary_id: uuid.UUID
    patient_id: uuid.UUID
    user_id: uuid.UUID
    authorization: str
    request_id: str | None
    force: bool = False
    scenario: str | None = None
    started: float = field(default_factory=time.monotonic)
    deadline_s: float = 90.0
    attempts: int = 0
    tool_calls: int = 0
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_estimated: bool = False
    force_final: bool = False

    @property
    def call(self) -> CallContext:
        return CallContext(self.authorization, self.request_id)

    def remaining(self) -> float:
        return self.deadline_s - (time.monotonic() - self.started)

    def latency_ms(self) -> int:
        return round((time.monotonic() - self.started) * 1000)


@dataclass
class State:
    """What the pipeline has built so far; decides whether a late failure is 'failed' or 'degraded'."""
    chart: Chart | None = None
    latest: Latest | None = None
    trends: Trends | None = None
    builder: RefBuilder | None = None
    facts: dict[str, Any] | None = None
    gaps: dict[str, Any] | None = None
    packet: dict[str, Any] | None = None
    trimmed: list[str] = field(default_factory=list)
    hash_inputs: HashInputs | None = None
    context_hash: str | None = None


class _Degrade(Exception):
    def __init__(self, code: str, step: str, note: str) -> None:
        super().__init__(code)
        self.code, self.step, self.note = code, step, note


class _Fail(Exception):
    def __init__(self, code: str, step: str, note: str) -> None:
        super().__init__(code)
        self.code, self.step, self.note = code, step, note


NOTES = {
    "LLM_TIMEOUT": "AI service did not respond in time", "LLM_UNAVAILABLE": "AI service unavailable",
    "LLM_RATE_LIMITED": "AI service at its usage limit", "LLM_CIRCUIT_OPEN": "AI service temporarily unavailable",
    "LLM_BUSY": "AI service busy", "LLM_INVALID_OUTPUT": "AI response could not be verified",
    "INTERNAL_ERROR": "Something went wrong",
}


def plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


class SummaryOrchestrator:
    def __init__(self, settings: Settings, sessionmaker: SessionMaker, patients: PatientClient, labs: LabClient,
                 llm: ResilientLLM, prompts: PromptSet, clock: Clock, registry: Any | None = None) -> None:
        self.s, self._sm, self._patients, self._labs = settings, sessionmaker, patients, labs
        self.llm, self.prompts, self._clock, self.registry = llm, prompts, clock, registry
        self._tz = ZoneInfo(settings.clinic_tz)
        self._rule_cfg = RuleConfig(no_recent_labs_days=settings.no_recent_labs_days,
                                    egfr_discordance_tolerance=settings.egfr_discordance_tolerance,
                                    no_stage_lt60_min_days=settings.no_stage_lt60_min_days)

    @property
    def tools_enabled(self) -> bool:
        return bool(self.s.llm_tools_enabled and self.llm.capabilities.supports_tools and self.registry is not None)

    # ================================================================================================
    async def run(self, job: JobContext, tracker: ProgressTracker | None = None) -> None:
        tracker = tracker or ProgressTracker(job.summary_id, self._sm)
        state = State()
        heartbeat = asyncio.create_task(self._heartbeat(job))
        try:
            async with asyncio.timeout(job.deadline_s):
                await self._pipeline(job, tracker, state)
        except JobGone:
            log.warning("job.gone", extra={"summary_id": str(job.summary_id)})      # reaped: no further writes
        except _Fail as e:
            await self._finish_failed(job, tracker, e.code, e.step, e.note)
        except _Degrade as e:
            await self._finish_degraded(job, tracker, state, e.code, e.step, e.note)
        except TimeoutError:
            # deadline: facts built -> degraded LLM_TIMEOUT; before that -> failed UPSTREAM_TIMEOUT
            if state.facts is not None and state.gaps is not None:
                await self._finish_degraded(job, tracker, state, "LLM_TIMEOUT", self._running_step(tracker),
                                            NOTES["LLM_TIMEOUT"])
            else:
                await self._finish_failed(job, tracker, "UPSTREAM_TIMEOUT", self._running_step(tracker),
                                          "Loading the record took too long")
        except asyncio.CancelledError:
            # SIGTERM: one best-effort write, then let the cancellation continue (5 s grace)
            with contextlib.suppress(Exception):
                async with asyncio.timeout(5):
                    await asyncio.shield(self._finish_failed(job, tracker, "JOB_ABORTED", self._running_step(tracker),
                                                             "Interrupted"))
            raise
        except Exception as exc:
            log.error("job.unexpected_error", extra={"summary_id": str(job.summary_id),
                                                     "error_type": type(exc).__name__}, exc_info=exc)
            with contextlib.suppress(Exception):
                if state.facts is not None and state.gaps is not None:
                    await self._finish_degraded(job, tracker, state, "INTERNAL_ERROR", self._running_step(tracker),
                                                NOTES["INTERNAL_ERROR"])
                else:
                    await self._finish_failed(job, tracker, "INTERNAL_ERROR", self._running_step(tracker),
                                              NOTES["INTERNAL_ERROR"])
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat

    @staticmethod
    def _running_step(tracker: ProgressTracker) -> str:
        return next((s["key"] for s in tracker.steps if s["state"] == "running"), "save")

    async def _heartbeat(self, job: JobContext) -> None:
        """A ticker keeps the reaper away from slow but healthy jobs while a step waits on a provider (B7.4)."""
        while True:
            await asyncio.sleep(self.s.heartbeat_interval_s)
            try:
                async with self._sm() as s, s.begin():
                    await repo.heartbeat(s, job.summary_id)
            except Exception as exc:       # a missed beat is harmless; the next one tries again
                log.warning("heartbeat.failed", extra={"error_type": type(exc).__name__})

    # ================================================================================================
    async def _pipeline(self, job: JobContext, tr: ProgressTracker, st: State) -> None:
        # 1 open_chart ------------------------------------------------------------------------------
        await tr.done("open_chart", "Ready")

        # 2 gather ----------------------------------------------------------------------------------
        await tr.start("gather")
        try:
            if job.scenario == "upstream_down" and self.s.app_env == "dev" and self.llm.name == "mock":
                raise UpstreamUnavailable("patient-svc")                 # demo option: simulated outage
            st.chart, st.latest, st.trends = await gather_all(
                self._patients.chart(job.patient_id, job.call), self._labs.latest(job.patient_id, job.call),
                self._labs.trends(job.patient_id, job.call))
        except PatientNotFound:
            raise _Fail("PATIENT_NOT_FOUND", "gather", "Patient record not found") from None
        except UpstreamTimeout:
            raise _Fail("UPSTREAM_TIMEOUT", "gather", "Loading the record took too long") from None
        except UpstreamUnavailable:
            raise _Fail("UPSTREAM_UNAVAILABLE", "gather", "Could not load the record") from None
        await tr.done("gather", "Done")

        # 3 rules -----------------------------------------------------------------------------------
        await tr.start("rules")
        today = self._clock().astimezone(self._tz).date()
        facts_in = from_chart(st.chart, st.latest, st.trends, today=today)
        findings = evaluate(facts_in, today=today, now=self._clock(), tz=self._tz, cfg=self._rule_cfg)
        st.builder = RefBuilder(self._tz)
        st.facts = build_facts(st.chart, st.latest, st.trends, st.builder)
        st.gaps = build_gaps(findings, st.chart, st.builder)
        await tr.done("rules", f"{plural(len(findings), 'rule finding')}, "
                               f"{plural(len(st.facts['abnormal_results']), 'abnormal result')}")

        # 4 prepare ---------------------------------------------------------------------------------
        await tr.start("prepare")
        packet = build_packet(st.chart, st.latest, st.trends, findings, today=today, builder=st.builder)
        st.packet, st.trimmed = trim_to_budget(packet, self.s.llm_context_max_chars)
        st.hash_inputs = HashInputs(PACKET_VERSION, self.prompts.version, SCHEMA_VERSION, RULES_VERSION,
                                    self.llm.name, self.llm.model, self.tools_enabled)
        st.context_hash = context_hash(job.patient_id, st.packet, st.hash_inputs)
        if not job.force:
            async with self._sm() as s:
                source = await repo.find_cache_source(s, job.patient_id, st.context_hash)
            if source is not None:
                await self._finish_cache_hit(job, tr, st, source["id"])
                return
        await tr.done("prepare", "New or changed data")

        # 5 write -----------------------------------------------------------------------------------
        await tr.start("write")
        text, messages = await self._write(job, tr, st)
        await tr.done("write", "Done")

        # 6 check -----------------------------------------------------------------------------------
        await tr.start("check")
        verdict, repaired, first_codes = await self._check(job, st, text, messages)
        if verdict.kind != "accept" or verdict.output is None:
            AI_VALIDATION.labels("rejected").inc()
            raise _Degrade("LLM_INVALID_OUTPUT", "check", NOTES["LLM_INVALID_OUTPUT"])
        AI_VALIDATION.labels("redacted" if verdict.safety_flags else "repaired" if repaired else "accepted").inc()
        await tr.done("check", f"{verdict.refs_resolved} of {verdict.refs_total} sources found in the record")

        # 7 save ------------------------------------------------------------------------------------
        await tr.start("save")
        await tr.done("save", "Saved")
        await self._finish_completed(job, tr, st, verdict, repaired, first_codes)

    # ------------------------------------------------------------------------------------------------
    async def _write(self, job: JobContext, tr: ProgressTracker, st: State) -> tuple[str, list[Message]]:
        """The LLM loop with optional tools (B8.3). Returns the last reply text and the conversation."""
        assert st.packet is not None
        packet_json = json.dumps(st.packet, ensure_ascii=False, separators=(",", ":"))
        messages = [Message("user", self.prompts.render_user(packet_json))]
        cap = self.llm.capabilities
        use_tools = self.tools_enabled
        schema = self.prompts.output_schema
        for iteration in range(1, self.s.llm_max_tool_iterations + 1):
            budget_spent = job.tool_calls >= self.s.llm_max_tool_calls
            final_turn = (iteration == self.s.llm_max_tool_iterations or not use_tools or budget_spent
                          or job.force_final)
            with_json = final_turn or cap.json_with_tools
            req = LLMRequest(
                system=self.prompts.system, messages=list(messages),
                tools=None if final_turn else self.registry.definitions(),
                json_mode=with_json and cap.supports_json_mode,
                response_schema=schema if cap.supports_response_schema and with_json else None,
                temperature=self.s.llm_temperature, max_output_tokens=self.s.llm_max_output_tokens,
                timeout_s=self.s.llm_timeout_s,
                extra={"mock_scenario": job.scenario} if self.llm.name == "mock" and job.scenario else {})
            resp = await self._generate(job, tr, req)
            if resp.tool_calls and not final_turn:
                await tr.note("write", describe(resp.tool_calls))
                messages.append(Message("assistant", resp.text, tuple(resp.tool_calls)))
                allowed = resp.tool_calls[: self.s.llm_max_calls_per_turn]
                for call in allowed:
                    result = await self.registry.execute(call, job, iteration)
                    messages.append(Message("tool", result.to_message(), tool_call_id=call.id, name=call.name))
                if len(resp.tool_calls) > len(allowed):
                    messages.append(Message("user", f"Only the first {len(allowed)} tool calls were run."))
                continue
            if parse_lenient(resp.text) is None and not final_turn:
                job.force_final = True                  # next turn: no tools, JSON mode on
                messages.append(Message("assistant", resp.text or ""))
                continue
            return resp.text or "", messages
        raise AssertionError("unreachable: the last iteration is always a final turn")   # pragma: no cover

    async def _generate(self, job: JobContext, tr: ProgressTracker, req: LLMRequest) -> LLMResponse:
        async def on_wait() -> None:
            await tr.note("write", "Waiting for an AI slot")

        try:
            resp = await self.llm.generate(req, deadline_left=job.remaining, on_wait=on_wait)
        except (LLMCircuitOpen, LLMBusy) as e:
            raise _Degrade(e.code, "write", NOTES[e.code]) from None      # never reached the provider: no quota
        except LLMError as e:
            job.attempts += 1
            raise _Degrade(e.code, "write", NOTES.get(e.code, NOTES["LLM_UNAVAILABLE"])) from None
        job.attempts += 1
        self._count_tokens(job, req, resp)
        return resp

    def _count_tokens(self, job: JobContext, req: LLMRequest, resp: LLMResponse) -> None:
        if resp.tokens_in is None or resp.tokens_out is None:
            job.tokens_estimated = True
            tin = (len(req.system) + sum(len(m.content or "") for m in req.messages)) // 4
            tout = len(resp.text or "") // 4
        else:
            tin, tout = resp.tokens_in, resp.tokens_out
        job.tokens_in += tin
        job.tokens_out += tout
        LLM_TOKENS.labels(self.llm.name, "in").inc(tin)
        LLM_TOKENS.labels(self.llm.name, "out").inc(tout)

    async def _check(self, job: JobContext, st: State, text: str,
                     messages: list[Message]) -> tuple[Verdict, bool, list[str]]:
        """Validate, repair once (tools off, JSON on), validate again (B9.6)."""
        assert st.packet is not None and st.builder is not None
        allowed: set[Decimal] = allowed_numbers(st.packet, job.tool_results)
        v = validate(text, st.builder.index, allowed, attempt=1)
        if v.kind == "accept":
            return v, False, []
        first_codes = list(v.reason_codes)
        messages = [*messages, Message("assistant", text), Message("user", self.prompts.render_repair(v.reasons))]
        req = LLMRequest(system=self.prompts.system, messages=messages, tools=None, json_mode=True,
                         response_schema=None, temperature=self.s.llm_temperature,
                         max_output_tokens=self.s.llm_max_output_tokens, timeout_s=self.s.llm_timeout_s,
                         extra={"mock_scenario": job.scenario} if self.llm.name == "mock" and job.scenario else {})
        resp = await self._generate(job, _NoTracker(), req)
        return validate(resp.text, st.builder.index, allowed, attempt=2), True, first_codes

    # ================================================================================================
    # Final writes. Each is ONE statement guarded by status = 'running'; the CHECK constraints validate its shape.
    # ================================================================================================
    def _snapshot(self, job: JobContext, st: State) -> dict[str, Any]:
        assert st.builder is not None and st.hash_inputs is not None
        return {"packet": st.packet, "ref_index": st.builder.index.to_json(), "tool_results": job.tool_results,
                "trimmed": st.trimmed, "hash_inputs": asdict(st.hash_inputs)}

    async def _write_final(self, job: JobContext, status: str, **fields: Any) -> bool:
        async with self._sm() as s, s.begin():
            ok = await repo.finish(s, job.summary_id, status, latency_ms=job.latency_ms(), **fields)
        return ok

    def _log_finished(self, job: JobContext, status: str, code: str | None, cached: bool,
                      v: Verdict | None = None, repaired: bool = False) -> None:
        AI_SUMMARIES.labels(status, code or "", str(cached).lower()).inc()
        AI_SUMMARY_DURATION.labels(status).observe(job.latency_ms() / 1000)
        log.info("summary.finished", extra={
            "summary_id": str(job.summary_id), "status": status, "error_code": code, "cached": cached,
            "attempts": job.attempts, "tool_calls": job.tool_calls, "repaired": repaired,
            "refs_total": v.refs_total if v else None, "refs_stripped": v.refs_stripped if v else None,
            "safety_flags": v.safety_flags if v else None,
            "grounding_warnings": len(v.grounding_warnings) if v else None,
            "tokens_in": job.tokens_in, "tokens_out": job.tokens_out, "latency_ms": job.latency_ms()})

    async def _finish_cache_hit(self, job: JobContext, tr: ProgressTracker, st: State, original: uuid.UUID) -> None:
        await tr.done("prepare", "Same data as an earlier summary")
        tr.skip(["write", "check", "save"], "Not needed, reusing the saved summary")
        ok = await self._write_final(job, "completed", cached_from=original, context_hash=st.context_hash,
                                     progress=tr.steps, attempts=0)
        if ok:
            self._log_finished(job, "completed", None, True)

    async def _finish_completed(self, job: JobContext, tr: ProgressTracker, st: State, v: Verdict, repaired: bool,
                                first_codes: list[str]) -> None:
        assert v.output is not None and st.facts is not None and st.gaps is not None and st.builder is not None
        sources = hydrate_sources(refs_in_output(v.output) | refs_in_blocks(st.facts, st.gaps), st.builder.index)
        block = ValidationBlock(
            schema_valid=True, refs_total=v.refs_total, refs_resolved=v.refs_resolved, refs_stripped=v.refs_stripped,
            grounding_warnings=[f"{w['field']}: {w['number']}" for w in v.grounding_warnings],
            safety_flags=v.safety_flags, safety_warnings=v.safety_warnings,
            safety_redactions=[f"{r['field']}: {r['rule']}" for r in v.safety_redactions], attempts=job.attempts,
            repaired=repaired, repair_reasons=first_codes if repaired else [], tool_calls=job.tool_calls,
            tokens_estimated=job.tokens_estimated)
        ok = await self._write_final(
            job, "completed", context_hash=st.context_hash, context_snapshot=self._snapshot(job, st), facts=st.facts,
            gaps=st.gaps, output=v.output, sources=sources, validation=block.model_dump(), progress=tr.steps,
            attempts=job.attempts, tool_call_count=job.tool_calls, tokens_in=job.tokens_in, tokens_out=job.tokens_out)
        if ok:
            self._log_finished(job, "completed", None, False, v, repaired)

    async def _finish_degraded(self, job: JobContext, tr: ProgressTracker, st: State, code: str, step: str,
                               note: str) -> None:
        """Facts and rule findings are saved; the AI part is unavailable or invalid (B10.4)."""
        tr.mark_failed(step, note)
        fields: dict[str, Any] = dict(facts=st.facts, gaps=st.gaps, error_code=code, progress=tr.steps,
                                      attempts=job.attempts, tool_call_count=job.tool_calls,
                                      tokens_in=job.tokens_in or None, tokens_out=job.tokens_out or None)
        if st.context_hash and st.builder is not None and st.hash_inputs is not None:
            fields.update(context_hash=st.context_hash, context_snapshot=self._snapshot(job, st))
        if await self._write_final(job, "degraded", **fields):
            self._log_finished(job, "degraded", code, False)

    async def _finish_failed(self, job: JobContext, tr: ProgressTracker, code: str, step: str, note: str) -> None:
        tr.mark_failed(step, note)
        if await self._write_final(job, "failed", error_code=code, progress=tr.steps, attempts=job.attempts,
                                   tool_call_count=job.tool_calls):
            self._log_finished(job, "failed", code, False)


class _NoTracker:
    """The repair call has no progress note of its own."""

    async def note(self, key: str, note: str) -> None:
        return None


def describe(calls: list[ToolCall]) -> str:
    names = {"get_lab_trend": "lab trend", "get_lab_history": "lab history",
             "get_recent_encounters": "recent encounters",
             "get_conditions": "conditions", "get_medications_and_allergies": "medications and allergies",
             "get_gap_report": "rule findings"}
    parts = []
    for c in calls[:3]:
        what = names.get(c.name, "record details")
        code = c.arguments.get("test_code") if isinstance(c.arguments, dict) else None
        parts.append(f"{what} {code}" if isinstance(code, str) and len(code) < 12 else what)
    return "Looking up " + ", ".join(parts)

