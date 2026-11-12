"""Minimization (LLD B5.4) and the packet budget (B5.5). PURE.

Whitelist by construction (the packet builder copies only listed fields), scrub free text, truncate, and trim to
budget in a fixed order, recording every step.
"""
from __future__ import annotations

import copy
import json
import re
from typing import Any

REDACTED = "[redacted]"
TRUNCATED = "…[truncated]"
FREE_TEXT_MAX = 1500
HISTORY_TRIMMED_MAX = 500

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_MRN = re.compile(r"\bPT-\d{6,}\b", re.IGNORECASE)
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_PHONE = re.compile(r"(?<![\w.])\+?[0-9][0-9 ()\-]{5,}[0-9](?![\w])")


def scrub(text: str) -> str:
    """Email addresses, MRN patterns and phone-like sequences (>= 7 digits) become ``[redacted]``.
    Names inside narrative cannot be removed reliably by a regex (B5.4): acceptable for synthetic data only."""
    text = _EMAIL.sub(REDACTED, text)
    text = _MRN.sub(REDACTED, text)

    def phone(m: re.Match[str]) -> str:
        if _ISO_DATE.fullmatch(m.group()):          # 2023-02-10 has eight digits but is a date, not a number
            return m.group()
        return REDACTED if sum(c.isdigit() for c in m.group()) >= 7 else m.group()

    return _PHONE.sub(phone, text)


def clean_text(value: str | None, limit: int = FREE_TEXT_MAX) -> str | None:
    if value is None or not value.strip():
        return None
    out = scrub(value.strip())
    return out if len(out) <= limit else out[:limit].rstrip() + TRUNCATED


def size(packet: dict[str, Any]) -> int:
    return len(json.dumps(packet, ensure_ascii=False, separators=(",", ":"), default=str))


def trim_to_budget(packet: dict[str, Any], max_chars: int) -> tuple[dict[str, Any], list[str]]:
    """Trim in order until it fits: (1) examination of the older recent encounter, (2) its assessment and plan,
    (3) drop it, (4) history texts to 500 chars, (5) discontinued medications. Labs, CKD, trends and rule findings
    are never trimmed: they are small and they are the facts."""
    p = copy.deepcopy(packet)
    trimmed: list[str] = []
    if size(p) <= max_chars:
        return p, trimmed
    recent: list[dict[str, Any]] = p["encounters"]["recent"]

    def older() -> dict[str, Any] | None:
        return recent[1] if len(recent) > 1 else None

    steps: list[tuple[str, Any]] = [
        ("older_encounter_examination", lambda: older() and older().update(examination=None)),
        ("older_encounter_assessment_plan", lambda: older() and older().update(assessment=None, plan=None)),
        ("older_encounter_dropped", lambda: recent.pop(1) if len(recent) > 1 else None),
        ("history_truncated", lambda: _shorten_history(p)),
        ("discontinued_medications_removed",
         lambda: p.__setitem__("medications", [m for m in p["medications"] if m["status"] == "active"])),
    ]
    for name, action in steps:
        action()
        trimmed.append(name)
        if size(p) <= max_chars:
            break
    return p, trimmed


def _shorten_history(p: dict[str, Any]) -> None:
    for key in ("past_medical_history", "family_history", "social_history"):
        block = p["patient"].get(key)
        if block and block.get("text") and len(block["text"]) > HISTORY_TRIMMED_MAX:
            block["text"] = block["text"][:HISTORY_TRIMMED_MAX].rstrip() + TRUNCATED
