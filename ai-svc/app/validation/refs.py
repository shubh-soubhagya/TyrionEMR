"""Citation check (LLD B9.3). PURE.

Every ref must match the grammar and resolve in the RefIndex. Unknown refs are stripped and counted, never trusted.
"""
from __future__ import annotations

from typing import Any

from app.context.refs import RefIndex, is_valid_ref


def strip_unknown_refs(raw: dict[str, Any], index: RefIndex) -> tuple[dict[str, Any], int, set[str], set[str]]:
    """Returns (cleaned copy, stripped_count, kept_refs, sections_emptied_by_stripping).

    Only ``source_refs`` lists of strings are touched; anything structurally wrong is left for the schema stage to
    report with a proper field path."""
    stripped = 0
    kept: set[str] = set()
    emptied: set[str] = set()

    def clean(path: str, holder: Any) -> None:
        nonlocal stripped
        if not isinstance(holder, dict) or not isinstance(holder.get("source_refs"), list):
            return
        original = holder["source_refs"]
        good: list[Any] = []
        for r in original:
            if isinstance(r, str) and is_valid_ref(r) and r in index:
                if r not in good:
                    good.append(r)
            else:
                stripped += 1
        holder["source_refs"] = good
        kept.update(good)
        if original and not good:
            emptied.add(path)

    out = {k: (dict(v) if isinstance(v, dict) else list(v) if isinstance(v, list) else v) for k, v in raw.items()}
    for name in ("history_summary", "comorbidity_summary", "trend_commentary", "abnormal_commentary"):
        clean(name, out.get(name))
    follow = out.get("follow_up_considerations")
    if isinstance(follow, list):
        out["follow_up_considerations"] = [dict(f) if isinstance(f, dict) else f for f in follow]
        for i, f in enumerate(out["follow_up_considerations"]):
            clean(f"follow_up_considerations[{i}]", f)
    return out, stripped, kept, emptied
