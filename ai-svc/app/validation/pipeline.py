"""The validation pipeline (LLD B9.1, B9.5, B9.6). PURE: text in, verdict out.

parse -> citations -> schema -> missing-information -> numeric grounding -> safety -> verdict.
LLM output is untrusted external input: nothing leaves this function unless it passed, was repaired once, or was
redacted. ``attempt`` is 1 for the first reply and 2 for the repair reply.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

from pydantic import ValidationError

from app.context.refs import RefIndex
from app.validation.numbers import ungrounded
from app.validation.output_schema import SummaryOutput
from app.validation.refs import strip_unknown_refs
from app.validation.safety import REMOVED, redact, scan

SECTIONS = ("history_summary", "comorbidity_summary", "trend_commentary", "abnormal_commentary")
NOT_DOCUMENTED = "Not documented."


@dataclass
class Verdict:
    kind: Literal["accept", "repair", "reject"]
    reasons: list[str] = field(default_factory=list)            # human-readable, for repair.md
    reason_codes: list[str] = field(default_factory=list)       # PARSE | SCHEMA | REFS | NOT_DOCUMENTED | SAFETY
    output: dict[str, Any] | None = None
    refs_total: int = 0
    refs_resolved: int = 0
    refs_stripped: int = 0
    grounding_warnings: list[dict[str, str]] = field(default_factory=list)
    safety_flags: int = 0
    safety_warnings: int = 0
    safety_redactions: list[dict[str, str]] = field(default_factory=list)


def parse_lenient(text: str | None) -> dict[str, Any] | None:
    """Strips code fences and takes the first balanced ``{...}`` object (respecting strings)."""
    if not text:
        return None
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            c = text[i]
            if in_str:
                esc = (c == "\\") and not esc
                if c == '"' and not esc:
                    in_str = False
                continue
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start:i + 1])
                    except ValueError:
                        break
                    return obj if isinstance(obj, dict) else None
        start = text.find("{", start + 1)
    return None


def _short(msg: str) -> str:
    return msg.replace("\n", " ")[:60]


def _schema_reasons(exc: ValidationError) -> list[str]:
    return [f"{'.'.join(str(p) for p in e['loc'])}: {_short(e['msg'])}" for e in exc.errors()[:8]]


def validate(raw_text: str | None, index: RefIndex, allowed: set[Decimal], *, attempt: int) -> Verdict:
    """One pass over stages 1-6. ``attempt`` 2 turns blocking safety hits into redactions instead of a repair."""
    v = Verdict("accept")
    raw = parse_lenient(raw_text)
    if raw is None:
        return _fail(v, attempt, ["Reply was not valid JSON"], ["PARSE"])

    cleaned, stripped, kept, emptied = strip_unknown_refs(raw, index)
    v.refs_stripped, v.refs_resolved, v.refs_total = stripped, len(kept), len(kept)

    try:
        model = SummaryOutput.model_validate(cleaned)
    except ValidationError as exc:
        return _fail(v, attempt, _schema_reasons(exc), ["SCHEMA"])
    out = model.model_dump()

    # stage 5: a section without refs must say exactly "Not documented."
    reasons: list[str] = []
    codes: list[str] = []
    for name in SECTIONS:
        sec = out[name]
        if not sec["source_refs"] and sec["text"] != NOT_DOCUMENTED:
            reasons.append(f'{name}: has no valid source_refs, so the text must be exactly "{NOT_DOCUMENTED}"')
            codes.append("REFS" if name in emptied else "NOT_DOCUMENTED")
    if reasons:
        return _fail(v, attempt, reasons, codes)

    # stage 4: numeric grounding (warnings only)
    for name, text in _texts(out):
        for n in ungrounded(text, allowed):
            v.grounding_warnings.append({"field": name, "number": n})

    # stage 6: safety
    blocked: list[str] = []
    for name, text in _texts(out):
        for hit in scan(text, in_follow_up=name.startswith("follow_up_considerations")):
            if hit.level == "warn":
                v.safety_warnings += 1
            else:
                blocked.append(f'{name}: rule {hit.rule} matched "{hit.excerpt}"')
    if blocked and attempt == 1:
        return Verdict("repair", blocked, ["SAFETY"], refs_total=v.refs_total, refs_resolved=v.refs_resolved,
                       refs_stripped=v.refs_stripped, safety_warnings=v.safety_warnings)
    if blocked:
        _apply_redaction(out, v)
    v.output = out
    return v


def _texts(out: dict[str, Any]):
    for name in SECTIONS:
        yield name, out[name]["text"]
    for i, f in enumerate(out["follow_up_considerations"]):
        yield f"follow_up_considerations[{i}].consideration", f["consideration"]
        yield f"follow_up_considerations[{i}].rationale", f["rationale"]


def _apply_redaction(out: dict[str, Any], v: Verdict) -> None:
    for name in SECTIONS:
        new, fired = redact(out[name]["text"], in_follow_up=False)
        if fired:
            out[name]["text"] = new
            v.safety_flags += 1
            v.safety_redactions += [{"field": name, "rule": r} for r in dict.fromkeys(fired)]
    kept = []
    for i, f in enumerate(out["follow_up_considerations"]):
        for key in ("consideration", "rationale"):
            new, fired = redact(f[key], in_follow_up=True)
            if fired:
                f[key] = new
                v.safety_flags += 1
                v.safety_redactions += [{"field": f"follow_up_considerations[{i}].{key}", "rule": r}
                                        for r in dict.fromkeys(fired)]
        if f["consideration"].replace(REMOVED, "").strip() == "":        # fully redacted: dropped from the list
            continue
        kept.append(f)
    out["follow_up_considerations"] = kept


def _fail(v: Verdict, attempt: int, reasons: list[str], codes: list[str]) -> Verdict:
    v.reasons, v.reason_codes, v.output = reasons, codes, None
    v.kind = "repair" if attempt == 1 else "reject"
    return v
