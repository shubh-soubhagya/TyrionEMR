"""Password policy (LLD §19.6). Pure: no I/O. The server is authoritative; the SPA mirrors three rules."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from importlib import resources


@dataclass(frozen=True)
class Violation:
    code: str
    message: str


MIN_LEN, MAX_LEN = 10, 128


def check_password(password: str, email: str, common: frozenset[str]) -> list[Violation]:
    v: list[Violation] = []
    if len(password) < MIN_LEN:
        v.append(Violation("TOO_SHORT", "At least 10 characters."))
    if len(password) > MAX_LEN:
        v.append(Violation("TOO_LONG", "At most 128 characters."))
    if not any(c.isalpha() for c in password):
        v.append(Violation("NEEDS_LETTER", "Contains a letter and a number."))
    if not any(c.isdigit() for c in password):
        v.append(Violation("NEEDS_DIGIT", "Contains a letter and a number."))
    if password.lower() in common:
        v.append(Violation("TOO_COMMON", "Not a commonly used password."))
    local = email.split("@", 1)[0].lower()
    if len(local) >= 4 and local in password.lower():
        v.append(Violation("CONTAINS_EMAIL", "Must not contain your email name."))
    return v


@lru_cache
def load_common_passwords() -> frozenset[str]:
    text = resources.files("app.domain").joinpath("data/common_passwords.txt").read_text(encoding="utf-8")
    return frozenset(line.strip().lower() for line in text.splitlines() if line.strip())
