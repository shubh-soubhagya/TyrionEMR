import ast
import pathlib

import pytest

from app.routing.paths import UnsafePath, route_template, safe_segments

UUID = "0b7c1e2a-4d5f-4a6b-8c7d-0e1f2a3b5a69"


@pytest.mark.parametrize(
    ("raw", "segments"),
    [
        ("/api/patients", ["api", "patients"]),
        ("/api/patients/", ["api", "patients"]),
        ("/api/encounters", ["api", "encounters"]),
        ("/api/auth/login", ["api", "auth", "login"]),
        (f"/api/labs/patients/{UUID}/results", ["api", "labs", "patients", UUID, "results"]),
        ("/api/patients/a%7Eb", ["api", "patients", "a~b"]),     # benign escape: unreserved '~'
        ("/api", ["api"]),
        ("/", []),
    ],
)
def test_accepted(raw, segments):
    assert safe_segments(raw) == segments


@pytest.mark.parametrize(
    "raw",
    [
        "/api/labs/../internal/labs/status",
        "/api/labs/./x",
        "/api/labs/%2e%2e/internal",
        "/api/labs/%2E%2E/internal",
        "/api/labs/%252e%252e/internal",
        "/api//patients",
        "/api\\labs",
        "/api/labs/a%2fb",
        "/api/labs/a%2Fb",
        "/api/x%00",
        "/api/labs/%5c..",
        "/api/labs/<script>",
        "/api/patients/abc%20def",
        "/api/patients/a b",
        "api/patients",
        "/api/labs/%25",
        "/api/labs/%",
    ],
)
def test_refused(raw):
    with pytest.raises(UnsafePath):
        safe_segments(raw)


def test_template_replaces_uuids_and_numbers_only():
    assert route_template(["api", "labs", "patients", UUID, "results"]) == "/api/labs/patients/{id}/results"
    assert route_template(["api", "patients", "42"]) == "/api/patients/{id}"
    assert route_template(["api", "patients", "search"]) == "/api/patients/search"
    assert route_template([]) == "/"


def test_template_never_contains_an_identifier():
    t = route_template(safe_segments(f"/api/ai/patients/{UUID}/summary"))
    assert UUID not in t and t == "/api/ai/patients/{id}/summary"


def test_pure_modules_have_no_io_imports():
    """routing/ and domain/ import nothing from fastapi, starlette or httpx (ADR-G2, §16.3)."""
    root = pathlib.Path(__file__).resolve().parents[2] / "app"
    banned = {"fastapi", "starlette", "httpx"}
    offenders = []
    for folder in ("routing", "domain"):
        for f in (root / folder).glob("*.py"):
            for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                offenders += [f"{f.name}: {n}" for n in names if n.split(".")[0] in banned]
    assert offenders == []
