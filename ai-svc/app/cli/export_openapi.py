"""Writes docs/api/openapi.json from the app's own schema. Needs no database or network.

    python -m app.cli.export_openapi            # writes docs/api/openapi.json
    python -m app.cli.export_openapi --check    # exits 1 when the committed file is stale (CI)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "docs" / "api" / "openapi.json"


def render() -> str:
    os.environ.setdefault("AI_DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    os.environ.setdefault("APP_ENV", "dev")                 # production hides the schema routes, not app.openapi()
    from app.main import create_app

    return json.dumps(create_app().openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:
    text = render()
    if "--check" in argv:
        current = OUT.read_text(encoding="utf-8") if OUT.is_file() else ""
        if current.replace("\r\n", "\n") != text:
            print("docs/api/openapi.json is stale: run `make openapi`", file=sys.stderr)
            return 1
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
