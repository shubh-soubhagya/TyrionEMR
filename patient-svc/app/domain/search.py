"""Search-query parsing and sort map for the patient list (LLD §15). Pure functions."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

MRN_FULL = re.compile(r"^pt-?(\d{1,9})$", re.IGNORECASE)
DIGITS = re.compile(r"^\d{1,9}$")
MAX_TOKENS = 5
MAX_QUERY_LEN = 100

Kind = Literal["mrn_prefix", "mrn_digits", "name", "none"]


@dataclass(frozen=True)
class SearchSpec:
    kind: Kind
    value: str = ""
    tokens: tuple[str, ...] = field(default_factory=tuple)


def escape_like(token: str) -> str:
    """Escape LIKE wildcards; the SQL uses ``ESCAPE '\\'``."""
    return token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def parse_query(q: str | None) -> SearchSpec:
    q = " ".join((q or "").split())[:MAX_QUERY_LEN]
    if not q:
        return SearchSpec(kind="none")
    if m := MRN_FULL.match(q):
        # 'PT-000101', 'pt101', 'PT-0001': the digits are matched as an exact zero-padded MRN or as a prefix
        return SearchSpec(kind="mrn_digits", value=m.group(1))
    if DIGITS.match(q):
        return SearchSpec(kind="mrn_digits", value=q)                            # '101' -> exact padded or prefix
    tokens = tuple(escape_like(t.lower()) for t in q.split(" "))[:MAX_TOKENS]
    return SearchSpec(kind="name", tokens=tokens)


# (expression, descending-when-direction-is-asc). ``dir=desc`` flips every term (LLD §15.3).
SORT_TERMS: dict[str, tuple[tuple[str, bool], ...]] = {
    "name": (("lower(f.last_name)", False), ("lower(f.first_name)", False)),
    "mrn": (("f.mrn", False),),                   # zero-padded, so text order = numeric order
    "age": (("f.date_of_birth", True),),          # youngest first for ascending age
    # both keys are columns kept on the patient row (migration 0004), so the sort needs no lateral join
    "dx": (("f.primary_dx_sort", False),),
    "visit": (("f.last_visit_key", False),),
}
SORTS_NULLS_LAST = frozenset({"dx", "visit"})
SORT_KEYS = tuple(SORT_TERMS)


def default_direction(sort: str) -> Literal["asc", "desc"]:
    return "desc" if sort == "visit" else "asc"


def order_by_sql(sort: str, direction: str) -> str:
    """ORDER BY clause for a validated sort key. ``f.id`` is the final tie-breaker so paging is stable."""
    flip = direction == "desc"
    terms = [f"{expr} {'DESC' if desc != flip else 'ASC'}{' NULLS LAST' if sort in SORTS_NULLS_LAST else ''}"
             for expr, desc in SORT_TERMS[sort]]
    return ", ".join([*terms, "f.id"])
