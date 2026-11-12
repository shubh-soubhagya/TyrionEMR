"""Layering is enforced by import inspection (LLD §22): domain is pure, routers never touch repositories."""
from __future__ import annotations

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "app"


def imports_of(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            found.update(f"{node.module}.{a.name}" for a in node.names)
    return found


def violations(folder: str, forbidden: tuple[str, ...]) -> list[str]:
    bad = []
    for path in sorted((APP / folder).rglob("*.py")):
        if path.name == "health.py":          # /ready checks the database directly; it has no business logic
            continue
        for name in imports_of(path):
            if name.startswith(forbidden):
                bad.append(f"{path.relative_to(APP)} imports {name}")
    return bad


def test_domain_is_pure():
    assert violations("domain", ("app.api", "app.services", "app.repositories", "app.models", "app.db",
                                 "app.schemas", "sqlalchemy", "fastapi")) == []


def test_routers_never_import_repositories_or_models():
    assert violations("api/routes", ("app.repositories", "app.models", "sqlalchemy")) == []


def test_repositories_do_not_import_services_or_api():
    assert violations("repositories", ("app.services", "app.api")) == []
