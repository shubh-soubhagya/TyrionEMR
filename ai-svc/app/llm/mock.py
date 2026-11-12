"""MockProvider (LLD B7.5): deterministic, schema-valid output built from the packet's own refs, driven by scenarios.

With ``LLM_PROVIDER=mock`` and ``APP_ENV=dev`` the header ``X-Mock-Scenario`` selects the scenario per job (the
backend for the prototype's "Demo options"); in any other configuration the header is ignored.
"""
from __future__ import annotations

import json
from typing import Any

from app.llm.base import (
    Capabilities,
    LLMRateLimited,
    LLMRequest,
    LLMResponse,
    LLMTimeout,
    Message,
    ToolCall,
)

SCENARIOS = ("success", "tool_roundtrip", "invalid_then_valid", "invalid_twice", "bad_refs", "unsafe_then_safe",
             "unsafe_twice", "timeout", "rate_limited", "upstream_down")
UNSAFE = {"consideration": "Start amlodipine 5 mg daily.", "rationale": "Blood pressure was recorded at the visit."}


def _packet(messages: list[Message]) -> dict[str, Any]:
    first = next((m.content or "" for m in messages if m.role == "user"), "")
    start = first.find("PATIENT_RECORD:")
    end = first.find("\n\nOUTPUT_SCHEMA:")
    try:
        return json.loads(first[start + len("PATIENT_RECORD:"):end])
    except ValueError:
        return {}


def _refs(packet: dict[str, Any]) -> list[str]:
    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if isinstance(node.get("ref"), str):
                found.append(node["ref"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(packet)
    return found


def valid_output(packet: dict[str, Any], *, unsafe: bool = False) -> dict[str, Any]:
    refs = _refs(packet)

    def pick(*prefixes: str, limit: int = 6) -> list[str]:
        return [r for r in refs if r.startswith(prefixes)][:limit]

    def section(text: str, source_refs: list[str]) -> dict[str, Any]:
        if not source_refs:
            return {"text": "Not documented.", "source_refs": []}
        return {"text": text, "source_refs": source_refs}

    history = pick("pt:pmh", "pt:fh", "pt:sh", "enc:", limit=4)
    abnormal = [e["ref"] for e in packet.get("labs", {}).get("latest", []) if e.get("flag") not in ("normal", None)][:6]
    follow = []
    anchor = pick("trend:EGFR") or pick("trend:") or pick("lab:", limit=1)
    if unsafe and anchor:
        follow = [{**UNSAFE, "source_refs": anchor[:1]}]
    elif anchor and packet.get("labs", {}).get("trends", {}).get("EGFR", {}).get("rapid_decline"):
        follow = [{"consideration": "Consider reviewing the rate of eGFR decline at the next visit.",
                   "rationale": "The system flagged a rapid decline in eGFR.", "source_refs": anchor[:1]}]
    missing = []
    if not packet.get("labs", {}).get("latest"):
        missing.append("laboratory results")
    if not packet.get("medications"):
        missing.append("medications")
    return {
        "history_summary": section("Past history and recent encounters are recorded in the cited items.", history),
        "comorbidity_summary": section("Conditions are recorded as listed in the cited items.", pick("cond:")),
        "trend_commentary": section("Trends are as calculated by the system from the recorded results.",
                                    pick("trend:")),
        "abnormal_commentary": section("Abnormal results are as flagged by the laboratory rules.", abnormal),
        "follow_up_considerations": follow,
        "not_documented": missing,
    }


class MockProvider:
    name = "mock"
    capabilities = Capabilities(supports_tools=True, supports_json_mode=True, json_with_tools=True,
                                supports_response_schema=True, max_context_chars=200_000)

    def __init__(self, model: str = "mock-1", default_scenario: str = "success") -> None:
        self.model = model
        self.default_scenario = default_scenario

    async def generate(self, req: LLMRequest) -> LLMResponse:
        scenario = req.extra.get("mock_scenario") or self.default_scenario
        packet = _packet(req.messages)
        repairing = any(m.role == "user" and (m.content or "").startswith("Your previous reply was rejected")
                        for m in req.messages)
        tin = sum(len(m.content or "") for m in req.messages) // 4

        def reply(obj: dict[str, Any] | str) -> LLMResponse:
            text = obj if isinstance(obj, str) else json.dumps(obj)
            return LLMResponse(text, [], "stop", tin, len(text) // 4, 5)

        if scenario == "timeout":
            raise LLMTimeout("mock timeout")
        if scenario == "rate_limited":
            raise LLMRateLimited(retry_after=60)
        if scenario == "tool_roundtrip" and req.tools and not any(m.role == "tool" for m in req.messages):
            calls = [ToolCall("call_1", "get_lab_trend", {"test_code": "EGFR"}),
                     ToolCall("call_2", "get_recent_encounters", {"limit": 3})]
            return LLMResponse(None, calls, "tool_calls", tin, 20, 5)
        if scenario == "invalid_twice" or (scenario == "invalid_then_valid" and not repairing):
            return reply("this is not json")
        if scenario == "bad_refs" and not repairing:
            out = valid_output(packet)
            out["history_summary"] = {"text": "Past history is recorded in the cited items.",
                                      "source_refs": [*out["history_summary"]["source_refs"], "cond:99"]}
            return reply(out)
        if scenario == "unsafe_twice" or (scenario == "unsafe_then_safe" and not repairing):
            return reply(valid_output(packet, unsafe=True))
        return reply(valid_output(packet))
