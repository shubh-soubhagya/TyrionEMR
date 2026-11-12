"""Numeric grounding (LLD B9.4). PURE.

A number in the narrative must appear in the packet or tool results, allowing for rounding ("1.9" for 1.898).
Dates, years and ref ids are excluded; small counts (0-10) are always allowed. A miss is a *warning*, never a
failure: a model can legitimately write "two years" for ``span_days = 700``.
"""
from __future__ import annotations

import re
from collections.abc import Iterator
from decimal import Decimal, InvalidOperation
from typing import Any

NUM = re.compile(r"(?<![\w:#-])-?\d+(?:\.\d+)?(?![\w-])")
_MONTHS = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*"
_DATES = re.compile(rf"\b\d{{4}}-\d{{2}}-\d{{2}}\b|\b\d{{1,2}}\s+{_MONTHS}\.?\s+\d{{4}}\b|\b{_MONTHS}\.?\s+\d{{4}}\b"
                    r"|\b(?:19|20)\d{2}\b")


def strip_dates(text: str) -> str:
    return _DATES.sub(" ", text)


def _numbers_in(text: str) -> Iterator[Decimal]:
    for m in NUM.finditer(strip_dates(text)):
        try:
            yield abs(Decimal(m.group()))
        except InvalidOperation:       # pragma: no cover - the regex only yields valid numbers
            continue


def numeric_leaves(*docs: Any) -> Iterator[Decimal]:
    """Every number in the documents, including numbers written inside strings (BP 138/82, doses in notes).
    Values under a ``ref`` key are ids, not data."""
    stack: list[Any] = list(docs)
    while stack:
        node = stack.pop()
        if isinstance(node, bool) or node is None:
            continue
        if isinstance(node, (int, float, Decimal)):
            yield abs(Decimal(str(node)))
        elif isinstance(node, str):
            yield from _numbers_in(node)
        elif isinstance(node, dict):
            stack.extend(v for k, v in node.items() if k != "ref")
        elif isinstance(node, (list, tuple)):
            stack.extend(node)


def allowed_numbers(packet: dict[str, Any], tool_results: list[dict[str, Any]] | None = None) -> set[Decimal]:
    vals = set(numeric_leaves(packet, *(tool_results or [])))
    vals |= {Decimal(n) for n in range(0, 11)}
    return vals


def ungrounded(text: str, allowed: set[Decimal]) -> list[str]:
    misses: list[str] = []
    for m in NUM.finditer(strip_dates(text)):
        x = abs(Decimal(m.group()))
        places = max(0, -x.as_tuple().exponent)                  # type: ignore[operator]
        tol = Decimal(5).scaleb(-(places + 1))                   # x is an acceptable rounding of a
        if not any(abs(x - a) <= tol for a in allowed):
            misses.append(m.group())
    return misses
