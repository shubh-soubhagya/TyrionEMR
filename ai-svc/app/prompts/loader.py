"""Versioned prompt files (LLD B6). Loaded once at startup, hashed, never edited in place: a change is a new
version directory. Prompt text lives in Markdown files next to this module, not in code."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
_VERSION = re.compile(r"^v[0-9]+$")
FILES = ("system.md", "user.md", "repair.md", "output_schema.json")


@dataclass(frozen=True)
class PromptSet:
    version: str
    system: str
    user_template: str
    repair_template: str
    output_schema: dict[str, Any]
    sha256: str                      # over all four files: logged at startup, changes whenever a prompt changes

    def render_user(self, packet_json: str) -> str:
        # str.replace, not str.format: the packet and schema are full of braces
        return (self.user_template.replace("{packet_json}", packet_json)
                .replace("{output_schema_json}", json.dumps(self.output_schema, separators=(",", ":"))))

    def render_repair(self, reasons: list[str]) -> str:
        return self.repair_template.replace("{reasons}", "\n".join(f"- {r}" for r in reasons))


def load_prompts(version: str, root: Path = ROOT) -> PromptSet:
    if not _VERSION.match(version):
        raise ValueError(f"invalid prompt version {version!r}")
    base = root / version
    raw = {name: (base / name).read_text(encoding="utf-8") for name in FILES}   # FileNotFoundError = fail at startup
    digest = hashlib.sha256()
    for name in FILES:
        digest.update(name.encode() + b"\0" + raw[name].encode("utf-8"))
    return PromptSet(version, raw["system.md"].strip(), raw["user.md"].strip(), raw["repair.md"].strip(),
                     json.loads(raw["output_schema.json"]), digest.hexdigest())
