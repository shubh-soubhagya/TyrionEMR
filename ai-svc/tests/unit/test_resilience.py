"""LLM resilience and the mock provider (LLD B7.4, B7.5, B17.1)."""
from __future__ import annotations

import asyncio
import json

import pytest

from app.llm.base import (
    Capabilities,
    LLMAuthError,
    LLMBusy,
    LLMCircuitOpen,
    LLMRateLimited,
    LLMRequest,
    LLMResponse,
    LLMTimeout,
    LLMUnavailable,
    Message,
)
from app.llm.mock import MockProvider, valid_output
from app.llm.resilience import CircuitBreaker, ResilienceConfig, ResilientLLM

CAPS = Capabilities(True, True, True, False, 1000)


def req(**kw) -> LLMRequest:
    base = dict(system="s", messages=[Message("user", "hi")], tools=None, json_mode=True, response_schema=None,
                temperature=0.2, max_output_tokens=100, timeout_s=30)
    return LLMRequest(**(base | kw))


class Scripted:
    """Provider that plays back a list of results (exceptions are raised)."""
    name, model, capabilities = "scripted", "m", CAPS

    def __init__(self, *script):
        self.script, self.calls, self.timeouts = list(script), 0, []

    async def generate(self, r: LLMRequest) -> LLMResponse:
        self.calls += 1
        self.timeouts.append(r.timeout_s)
        item = self.script.pop(0) if self.script else LLMResponse("{}", [], "stop", 1, 1, 1)
        if isinstance(item, Exception):
            raise item
        return item


OK = LLMResponse("{}", [], "stop", 1, 1, 1)


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


async def no_sleep(_):
    return None


def make(provider, mono=None, **cfg):
    sleeps: list[float] = []

    async def sleep(s):
        sleeps.append(s)

    llm = ResilientLLM(provider, ResilienceConfig(**cfg), mono=mono or Clock(), sleep=sleep)
    llm.sleeps = sleeps
    return llm


def left(n=90.0):
    return lambda: n


# ---- circuit breaker ---------------------------------------------------------------------------
def test_breaker_opens_after_five_consecutive_failures_and_half_opens_after_the_cooldown():
    clock = Clock()
    b = CircuitBreaker("p", 5, 60, clock)
    for _ in range(4):
        b.failure()
    assert b.state == "closed" and b.allow()
    b.failure()
    assert b.state == "open" and not b.allow()
    clock.t = 59
    assert not b.allow()
    clock.t = 61
    assert b.state == "half_open"
    assert b.allow() and not b.allow()                  # exactly one probe
    b.success()
    assert b.state == "closed" and b.allow()


def test_failed_probe_reopens_the_breaker_for_a_full_cooldown():
    clock = Clock()
    b = CircuitBreaker("p", 2, 60, clock)
    b.failure()
    b.failure()
    clock.t = 61
    assert b.allow()
    b.failure()
    assert b.state == "open"
    clock.t = 100
    assert not b.allow()


def test_a_success_resets_the_failure_count():
    b = CircuitBreaker("p", 3, 60, Clock())
    for step in (b.failure, b.failure, b.success, b.failure, b.failure):
        step()
    assert b.state == "closed"


async def test_open_breaker_degrades_immediately_without_calling_the_provider():
    p = Scripted(*[LLMUnavailable()] * 20)
    llm = make(p, retries=0, breaker_failures=5)
    for _ in range(5):
        with pytest.raises(LLMUnavailable):
            await llm.generate(req(), deadline_left=left())
    calls = p.calls
    with pytest.raises(LLMCircuitOpen):
        await llm.generate(req(), deadline_left=left())
    assert p.calls == calls


# ---- retry -------------------------------------------------------------------------------------
async def test_timeout_is_retried_once_with_backoff_then_succeeds():
    p = Scripted(LLMTimeout(), OK)
    llm = make(p, retries=1)
    assert (await llm.generate(req(), deadline_left=left())).text == "{}"
    assert p.calls == 2 and len(llm.sleeps) == 1 and 0.5 <= llm.sleeps[0] <= 1.5


async def test_retries_are_bounded():
    p = Scripted(LLMUnavailable(), LLMUnavailable(), LLMUnavailable())
    llm = make(p, retries=1)
    with pytest.raises(LLMUnavailable):
        await llm.generate(req(), deadline_left=left())
    assert p.calls == 2


async def test_retry_is_skipped_when_the_deadline_does_not_allow_it():
    p = Scripted(LLMTimeout(), OK)
    llm = make(p, retries=1)
    with pytest.raises(LLMTimeout):
        await llm.generate(req(), deadline_left=left(2.4))      # backoff + 2 s margin does not fit
    assert p.calls == 1


async def test_each_http_timeout_is_min_of_setting_and_remaining_minus_two():
    p = Scripted(OK)
    await make(p, http_timeout_s=30).generate(req(), deadline_left=left(10))
    assert p.timeouts == [8]
    p2 = Scripted(OK)
    await make(p2, http_timeout_s=30).generate(req(), deadline_left=left(90))
    assert p2.timeouts == [30]


async def test_no_time_left_is_a_timeout_without_a_call():
    p = Scripted(OK)
    with pytest.raises(LLMTimeout):
        await make(p).generate(req(), deadline_left=left(1.5))
    assert p.calls == 0


# ---- 429 ---------------------------------------------------------------------------------------
async def test_429_waits_once_when_retry_after_is_within_the_cap():
    p = Scripted(LLMRateLimited(3), OK)
    llm = make(p, rate_limit_max_wait_s=10)
    assert (await llm.generate(req(), deadline_left=left())).text == "{}"
    assert llm.sleeps == [3]


async def test_429_beyond_the_cap_degrades_without_waiting():
    p = Scripted(LLMRateLimited(60), OK)
    llm = make(p, rate_limit_max_wait_s=10)
    with pytest.raises(LLMRateLimited):
        await llm.generate(req(), deadline_left=left())
    assert llm.sleeps == [] and p.calls == 1


async def test_429_is_waited_for_only_once_never_a_tight_loop():
    p = Scripted(LLMRateLimited(2), LLMRateLimited(2), OK)
    llm = make(p, rate_limit_max_wait_s=10)
    with pytest.raises(LLMRateLimited):
        await llm.generate(req(), deadline_left=left())
    assert p.calls == 2 and llm.sleeps == [2]


async def test_429_without_retry_after_is_not_waited_for():
    p = Scripted(LLMRateLimited(None), OK)
    with pytest.raises(LLMRateLimited):
        await make(p).generate(req(), deadline_left=left())


async def test_auth_errors_are_not_retried_and_do_not_open_the_breaker():
    p = Scripted(*[LLMAuthError()] * 10)
    llm = make(p, retries=3, breaker_failures=2)
    for _ in range(4):
        with pytest.raises(LLMAuthError):
            await llm.generate(req(), deadline_left=left())
    assert p.calls == 4 and llm.breaker.state == "closed"


# ---- concurrency -------------------------------------------------------------------------------
async def test_slot_limit_and_wait_timeout():
    gate = asyncio.Event()

    class Slow(Scripted):
        async def generate(self, r):
            await gate.wait()
            return OK

    llm = make(Slow(), max_concurrency=1, slot_wait_s=0.05)
    waits: list[str] = []

    async def on_wait():
        waits.append("waiting")

    first = asyncio.create_task(llm.generate(req(), deadline_left=left()))
    await asyncio.sleep(0.01)
    with pytest.raises(LLMBusy):
        await llm.generate(req(), deadline_left=left(), on_wait=on_wait)
    assert waits == ["waiting"]                                # the job is told it is waiting for a slot
    gate.set()
    await first
    assert (await llm.generate(req(), deadline_left=left())).text == "{}"      # slot released


# ---- mock provider -----------------------------------------------------------------------------
PACKET = {"patient": {"allergy_status": {"ref": "pt:allergy_status", "value": "nka"},
                      "past_medical_history": {"ref": "pt:pmh", "text": "x"}},
          "conditions": [{"ref": "cond:1"}], "medications": [], "encounters": {"recent": [{"ref": "enc:1"}]},
          "labs": {"latest": [{"ref": "lab:K:2026-10-21", "flag": "high"}, {"ref": "lab:CREAT:2026-10-21", "flag": "normal"}],
                   "trends": {"EGFR": {"ref": "trend:EGFR", "rapid_decline": True}}},
          "rule_findings": []}


def msgs(*extra):
    user = "PATIENT_RECORD:\n" + json.dumps(PACKET) + "\n\nOUTPUT_SCHEMA:\n{}\n\nWrite it."
    return [Message("user", user), *extra]


def test_valid_output_cites_only_refs_in_the_packet_and_is_schema_valid():
    from app.validation.output_schema import SummaryOutput
    out = valid_output(PACKET)
    SummaryOutput.model_validate(out)
    assert out["abnormal_commentary"]["source_refs"] == ["lab:K:2026-10-21"]
    assert out["follow_up_considerations"][0]["source_refs"] == ["trend:EGFR"]
    assert out["not_documented"] == ["medications"]


async def test_mock_scenarios():
    mock = MockProvider()
    ok = await mock.generate(req(messages=msgs()))
    assert json.loads(ok.text)["history_summary"]["source_refs"]
    bad = await mock.generate(req(messages=msgs(), extra={"mock_scenario": "invalid_then_valid"}))
    assert bad.text == "this is not json"
    repaired = await mock.generate(req(messages=msgs(Message("user", "Your previous reply was rejected for these reasons:\n- x")),
                                       extra={"mock_scenario": "invalid_then_valid"}))
    assert json.loads(repaired.text)
    with pytest.raises(LLMTimeout):
        await mock.generate(req(messages=msgs(), extra={"mock_scenario": "timeout"}))
    with pytest.raises(LLMRateLimited) as e:
        await mock.generate(req(messages=msgs(), extra={"mock_scenario": "rate_limited"}))
    assert e.value.retry_after == 60
    unsafe = json.loads((await mock.generate(req(messages=msgs(), extra={"mock_scenario": "unsafe_twice"}))).text)
    assert "mg" in unsafe["follow_up_considerations"][0]["consideration"]
    from app.llm.base import ToolDef
    tools = [ToolDef("x", "d", {})]
    first = await mock.generate(req(messages=msgs(), tools=tools, extra={"mock_scenario": "tool_roundtrip"}))
    assert [c.name for c in first.tool_calls] == ["get_lab_trend", "get_recent_encounters"]
    after = await mock.generate(req(messages=msgs(Message("tool", "{}", tool_call_id="c")), tools=tools,
                                    extra={"mock_scenario": "tool_roundtrip"}))
    assert not after.tool_calls and after.text
