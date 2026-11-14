#!/usr/bin/env python3
"""Writes the generated endpoint tables of docs/API.md from the four services' OpenAPI files. Standard library only.

The tables sit between <!-- BEGIN GENERATED --> and <!-- END GENERATED -->. `--check` exits 1 when the file would change.
Gateway paths and the public routes mirror gateway/app/routing/table.py: the route table is code, so a change there
must be repeated here (the two are small and reviewed together).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "docs" / "API.md"
BEGIN, END = "<!-- BEGIN GENERATED -->", "<!-- END GENERATED -->"

SERVICES = ("auth-svc", "patient-svc", "lab-svc", "ai-svc")
# first path segment -> routed by the gateway (gateway/app/routing/table.py: build_routes)
ROUTED_PREFIXES = {"auth", "patients", "encounters", "labs", "ai", "insights"}
# exact (method, service path) that need no token (gateway PUBLIC_ROUTES)
PUBLIC = {("POST", "/auth/login"), ("POST", "/auth/signup"), ("POST", "/auth/refresh"), ("POST", "/auth/logout")}
METHODS = ("get", "post", "put", "patch", "delete")


def operations(service: str) -> list[dict]:
    doc = json.loads((ROOT / service / "docs" / "api" / "openapi.json").read_text(encoding="utf-8"))
    rows: list[dict] = []
    for path, item in doc["paths"].items():
        for method in METHODS:
            op = item.get(method)
            if not op:
                continue
            success = next((c for c in op["responses"] if c.startswith("2")), "")
            query = [p["name"] for p in op.get("parameters", []) if p.get("in") == "query"]
            rows.append({"method": method.upper(), "path": path, "summary": op.get("summary", ""),
                         "query": query, "success": success})
    return rows


def reachable(path: str) -> bool:
    parts = [p for p in path.split("/") if p]
    return bool(parts) and parts[0] in ROUTED_PREFIXES


def esc(text: str) -> str:
    return text.replace("|", "\\|")


def caller_of(path: str) -> str:
    if path.startswith("/internal/"):
        return "ai-svc (private network)"
    if path in ("/health", "/ready"):
        return "Docker health check and the gateway's readiness probe"
    if path.endswith("jwks.json"):
        return "the gateway and the other services (token verification)"
    return "-"


def render() -> str:
    out: list[str] = []
    for service in SERVICES:
        rows = operations(service)
        routed = [r for r in rows if reachable(r["path"])]
        hidden = [r for r in rows if not reachable(r["path"])]
        out += [f"### {service}", "",
                f"Source: [{service}/docs/api/openapi.json](../{service}/docs/api/openapi.json). "
                f"{len(routed)} endpoints are reachable through the gateway.", "",
                "| Method | Gateway path | Summary | Auth | Query parameters | Success |", "|---|---|---|---|---|---|"]
        for r in routed:
            auth = "public" if (r["method"], r["path"]) in PUBLIC else "bearer"
            query = ", ".join(f"`{q}`" for q in r["query"]) or "-"
            out.append(f"| {r['method']} | `/api{esc(r['path'])}` | {esc(r['summary'])} | {auth} | {query} | {r['success']} |")
        out += ["", f"Not reachable through the gateway ({service}):", "",
                "| Method | Service path | Summary | Caller |", "|---|---|---|---|"]
        for r in hidden:
            out.append(f"| {r['method']} | `{esc(r['path'])}` | {esc(r['summary'])} | {caller_of(r['path'])} |")
        out.append("")
    return "\n".join(out)


def build(current: str) -> str:
    if BEGIN not in current or END not in current:
        raise SystemExit(f"{TARGET.relative_to(ROOT)} must contain {BEGIN} and {END}")
    head, rest = current.split(BEGIN, 1)
    _, tail = rest.split(END, 1)
    return f"{head}{BEGIN}\n\n{render()}\n{END}{tail}"


def main(argv: list[str]) -> int:
    current = TARGET.read_text(encoding="utf-8")
    new = build(current)
    if "--check" in argv:
        if new != current:
            print("docs/API.md is out of date: run `make docs`")
            return 1
        print("docs/API.md is up to date")
        return 0
    TARGET.write_text(new, encoding="utf-8", newline="\n")
    print("wrote the generated part of docs/API.md")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
