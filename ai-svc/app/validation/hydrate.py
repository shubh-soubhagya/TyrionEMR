"""Source hydration (LLD B9.7). PURE. Builds ``sources`` from the RefIndex for every ref the output cites, plus the
evidence refs of ``facts`` and ``gaps``, so every chip in every panel resolves. Refs that never resolve never reach
the client (they were stripped in B9.3)."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.context.refs import RefIndex


def refs_in_output(output: dict[str, Any]) -> set[str]:
    refs: set[str] = set()
    for name in ("history_summary", "comorbidity_summary", "trend_commentary", "abnormal_commentary"):
        refs.update(output.get(name, {}).get("source_refs", []))
    for f in output.get("follow_up_considerations", []):
        refs.update(f.get("source_refs", []))
    return refs


def refs_in_blocks(facts: dict[str, Any], gaps: dict[str, Any]) -> set[str]:
    refs: set[str] = set()
    if facts.get("ckd"):
        refs.add(facts["ckd"]["ref"])
    refs.update(a["ref"] for a in facts.get("abnormal_results", []))
    refs.update(t["ref"] for t in facts.get("trends", {}).values())
    for f in gaps.get("findings", []):
        refs.add(f["ref"])
        refs.update(f.get("evidence_refs", []))
    return refs


def hydrate_sources(refs: Iterable[str], index: RefIndex) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for ref in sorted(set(refs)):
        entry = index.get(ref)
        if entry is not None:
            out[ref] = {"type": entry.type, "label": entry.label, "tab": entry.tab, "target_id": entry.target_id}
    return out
