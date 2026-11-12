"""Import rules of A5, enforced by reading the source (no import side effects)."""
from __future__ import annotations

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "app"


def imports_of(package: str) -> set[str]:
    found: set[str] = set()
    for path in (APP / package).rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                found.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.add(node.module)
    return found


def assert_none(package: str, banned: tuple[str, ...]) -> None:
    hits = sorted(m for m in imports_of(package) if any(m == b or m.startswith(b + ".") for b in banned))
    assert not hits, f"{package} must not import {hits}"


def test_insights_never_depend_on_the_llm_side():
    banned = tuple(f"app.{p}" for p in ("llm", "orchestrator", "tools", "validation", "prompts", "jobs"))
    assert_none("insights", banned)


def test_rule_engine_is_pure():
    assert_none("insights/rules", ("fastapi", "sqlalchemy", "httpx", "app.clients.base", "app.clients.patient", "app.clients.lab",
                                 "app.repositories", "app.core.http"))


def test_context_and_validation_are_pure_when_they_exist():
    for pkg in ("context", "validation"):
        if (APP / pkg).is_dir():
            assert_none(pkg, ("fastapi", "sqlalchemy", "httpx"))


def test_routers_call_services_only():
    assert_none("api", ("app.repositories", "app.clients", "app.llm"))
