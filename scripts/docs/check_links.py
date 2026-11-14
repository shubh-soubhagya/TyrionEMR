#!/usr/bin/env python3
"""Checks every relative link and #anchor in the tracked Markdown files. Standard library only.

Exit 1 with a list when a link is broken. http(s) and mailto links are ignored. Anchors follow GitHub's rules:
lowercase, spaces to '-', punctuation removed, duplicates get -1, -2 ...
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
LINK = re.compile(r"(?<!\!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)|!\[[^\]]*\]\(([^)\s]+)\)")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
SKIP_DIRS = ("node_modules/", ".venv/")
# files that are records or third-party text, not documentation to keep link-clean
SKIP_FILES = ("gateway/docs/gaps.md", "ai-svc/app/prompts/")


def tracked_markdown() -> list[Path]:
    out = subprocess.run(["git", "ls-files", "*.md"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    paths = [ROOT / p for p in out.splitlines() if p and not p.startswith(SKIP_DIRS)]
    return [p for p in paths if not str(p.relative_to(ROOT)).replace("\\", "/").startswith(SKIP_FILES) and p.exists()]


def slug(text: str) -> str:
    text = re.sub(r"`([^`]*)`", r"\1", text)                  # inline code keeps its text
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)      # links keep their label
    text = re.sub(r"<[^>]+>", "", text).strip().lower()
    text = re.sub(r"[^\w\- ]", "", text, flags=re.UNICODE)
    return text.replace(" ", "-")


def anchors(path: Path) -> set[str]:
    seen: dict[str, int] = {}
    found: set[str] = set()
    in_fence = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        m = HEADING.match(line) if not in_fence else None
        if not m:
            continue
        base = slug(m.group(2))
        n = seen.get(base, 0)
        seen[base] = n + 1
        found.add(base if n == 0 else f"{base}-{n}")
    return found


def links(path: Path) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    in_fence = False
    for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        line = re.sub(r"`[^`]*`", "", line)                   # a link inside inline code is an example
        for m in LINK.finditer(line):
            out.append((no, m.group(1) or m.group(2)))
    return out


def main() -> int:
    cache: dict[Path, set[str]] = {}
    broken: list[str] = []
    for md in tracked_markdown():
        rel = md.relative_to(ROOT)
        for no, target in links(md):
            if re.match(r"^(https?:|mailto:|//)", target):
                continue
            file_part, _, frag = target.partition("#")
            dest = md if not file_part else (md.parent / unquote(file_part)).resolve()
            if not dest.exists():
                broken.append(f"{rel}:{no}: missing file {target}")
                continue
            if frag and dest.suffix == ".md":
                if dest not in cache:
                    cache[dest] = anchors(dest)
                if unquote(frag).lower() not in cache[dest]:
                    broken.append(f"{rel}:{no}: missing anchor {target}")
    if broken:
        print("\n".join(broken))
        print(f"\n{len(broken)} broken link(s)")
        return 1
    print("all relative links and anchors resolve")
    return 0


if __name__ == "__main__":
    sys.exit(main())
