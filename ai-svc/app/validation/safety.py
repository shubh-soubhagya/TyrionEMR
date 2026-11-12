"""Safety lint (LLD B9.5). PURE. Case-insensitive regular expressions with positive and negative tests.

S1-S4 block; S5 only warns. S2 (doses) applies to follow-up considerations only: "on losartan 50 mg" is a legitimate
history statement, "consider amlodipine 5 mg" is not.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

REMOVED = "[Removed by safety check]"
_I = re.IGNORECASE

_VERBS = (r"(?:start|initiate|prescribe|add|increase|decrease|reduce|titrate|stop|discontinue|hold|switch(?:\s+to)?"
          r"|starting|initiating|prescribing|adding|increasing|decreasing|reducing|titrating|stopping"
          r"|discontinuing|holding|switching(?:\s+to)?)")                  # not past tense: "was started in 2023"
_MED_TERMS = (r"(?:mg|mcg|µg|units?|dose|doses|dosing|tablets?|therapy|medications?|inhibitors?|blockers?"
              r"|diuretics?|statins?|insulin|ESA)")

S1 = re.compile(rf"\b{_VERBS}\b[^.;\n]{{0,40}}?\b{_MED_TERMS}\b", _I)
_DOSE = r"\b\d+(?:\.\d+)?\s?(?:mg|mcg|µg|ug|g|units?|IU|mL)\b(?!\s?/)"
S2 = re.compile(_DOSE, _I)                                  # 'mg/dL' and 'g/dL' are lab units, not doses
S3 = re.compile(r"\bnew diagnosis\b|\bdiagnosed (?:with|as)\b|\bconfirms? (?:the |a )?diagnosis\b"
                r"|\bthis (?:indicates|represents) (?:a )?diagnosis of\b|\byou have\b", _I)
S4 = re.compile(r"\badmit\b|\bhospitali[sz]e\b|\b(?:start|initiate)\s+dialysis\b|\bgo to the emergency\b", _I)
S5 = re.compile(r"\bcaused by\b|\bdue to\b|\bbecause of\b|\bdefinitely\b|\bcertainly\b|\bproves?\b", _I)

BLOCKING: tuple[tuple[str, re.Pattern[str], bool], ...] = (   # (rule, pattern, follow_up_only)
    ("S1", S1, False), ("S2", S2, True), ("S3", S3, False), ("S4", S4, False))
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class Hit:
    rule: str
    level: Literal["block", "warn"]
    excerpt: str                       # <= 60 chars, for the repair reason (model text is never echoed in full)


def scan(text: str, *, in_follow_up: bool) -> list[Hit]:
    hits: list[Hit] = []
    for rule, pattern, follow_only in BLOCKING:
        if follow_only and not in_follow_up:
            continue
        if m := pattern.search(text):
            hits.append(Hit(rule, "block", _excerpt(text, m)))
    if m := S5.search(text):
        hits.append(Hit("S5", "warn", _excerpt(text, m)))
    return hits


def redact(text: str, *, in_follow_up: bool) -> tuple[str, list[str]]:
    """Replaces only the offending *sentences*. Returns (new text, rules that fired)."""
    fired: list[str] = []
    out: list[str] = []
    for sentence in _SENTENCE_SPLIT.split(text):
        rules = [h.rule for h in scan(sentence, in_follow_up=in_follow_up) if h.level == "block"]
        if rules:
            fired.extend(rules)
            out.append(REMOVED)
        else:
            out.append(sentence)
    return " ".join(out), fired


def _excerpt(text: str, m: re.Match[str]) -> str:
    return text[max(0, m.start() - 10): m.end() + 10][:60]
