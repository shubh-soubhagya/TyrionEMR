"""Audit-integrity item 3: the env examples match Settings and the role split; the retire script is safe."""
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from pydantic import TypeAdapter

from app.core.config import Settings
from tests.conftest import ROOT

REPO = ROOT.parent
LINE = re.compile(r"^(#\s*)?([A-Z][A-Z0-9_]*)=(.*)$")
# example values that intentionally differ from the code default (developer-friendly or path-specific)
INTENTIONAL = {"AUTH_DATABASE_URL", "AUTH_MIGRATION_DATABASE_URL", "JWT_PRIVATE_KEY_PATH", "SEED_DEMO_USERS"}


def parse(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    """(active, commented) KEY -> value."""
    active, commented = {}, {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = LINE.match(line.strip())
        if m:
            (commented if m.group(1) else active)[m.group(2)] = m.group(3).strip()
    return active, commented


def host_port(url: str) -> tuple[str | None, int | None]:
    parts = urlsplit(url)
    return parts.hostname, parts.port


AUTH_ACTIVE, AUTH_COMMENTED = parse(ROOT / ".env.example")
ROOT_ACTIVE, _ = parse(REPO / ".env.example")


# --------------------------------------------------------------------------------- auth-svc example
def test_every_setting_is_listed_in_the_example():
    listed = set(AUTH_ACTIVE) | set(AUTH_COMMENTED)
    missing = sorted(name.upper() for name in Settings.model_fields if name.upper() not in listed)
    assert missing == [], f"settings missing from auth-svc/.env.example: {missing}"


def test_example_values_are_the_defaults_except_the_documented_ones():
    wrong = {}
    for name, field in Settings.model_fields.items():
        key = name.upper()
        if key not in AUTH_ACTIVE or key in INTENTIONAL or field.is_required():
            continue
        raw = AUTH_ACTIVE[key]
        if isinstance(field.default, list):
            parsed = [p.strip() for p in raw.split(",") if p.strip()]
        else:
            parsed = TypeAdapter(field.annotation).validate_python(raw)
        if parsed != field.default:
            wrong[key] = (raw, field.default)
    assert wrong == {}, f"example differs from the code default: {wrong}"


def test_the_example_uses_the_least_privilege_roles_on_port_5433():
    assert AUTH_ACTIVE["AUTH_APP_DB_USER"] == "auth_app"
    assert AUTH_ACTIVE["AUTH_MIGRATOR_DB_USER"] == "auth_migrator"
    expected = {"AUTH_DATABASE_URL": "auth_app", "AUTH_MIGRATION_DATABASE_URL": "auth_migrator",
                "AUTH_TEST_DATABASE_URL": "auth_app", "AUTH_TEST_MIGRATION_DATABASE_URL": "auth_migrator"}
    for key, user in expected.items():
        url = AUTH_ACTIVE[key]
        assert urlsplit(url).username == user, key
        assert host_port(url) == ("localhost", 5433), key
    assert AUTH_ACTIVE["AUTH_DATABASE_URL"].endswith("/nephro_auth_db")
    assert AUTH_ACTIVE["AUTH_TEST_DATABASE_URL"].endswith("/nephro_auth_db_test")


def test_the_example_has_no_trace_of_the_single_role_setup():
    text = "\n".join(line for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
                     if not line.lstrip().startswith("#"))
    assert "AUTH_DB_PW" not in text and "auth_svc" not in text


def test_the_retention_example_respects_the_floor():
    assert int(AUTH_ACTIVE["AUTH_EVENTS_RETENTION_DAYS"]) >= 30


# ------------------------------------------------------------------------------------ root example
def test_root_example_auth_section_uses_the_roles_and_has_no_legacy_password():
    assert "AUTH_DB_PW" not in ROOT_ACTIVE
    assert ROOT_ACTIVE["AUTH_APP_DB_USER"] == "auth_app" and ROOT_ACTIVE["AUTH_MIGRATOR_DB_USER"] == "auth_migrator"
    for key in ("AUTH_APP_DB_PW", "AUTH_MIGRATOR_DB_PW"):
        assert key in ROOT_ACTIVE
    text = (REPO / ".env.example").read_text(encoding="utf-8")
    assert not any("auth_svc" in line for line in text.splitlines() if not line.lstrip().startswith("#"))


def test_root_example_port_comment_matches_the_url():
    text = (REPO / ".env.example").read_text(encoding="utf-8")
    urls = [v for k, v in ROOT_ACTIVE.items() if k.startswith("AUTH_TEST") and k.endswith("URL")]
    assert urls and all(host_port(u) == ("localhost", 5433) for u in urls)
    # the old comment said "published port 5432" above a URL using 5433
    assert "published port 5432" not in text
    assert "port 5433" in text


def test_both_examples_name_the_same_role_variables():
    shared = {"AUTH_DB_NAME", "AUTH_APP_DB_USER", "AUTH_APP_DB_PW", "AUTH_MIGRATOR_DB_USER", "AUTH_MIGRATOR_DB_PW",
              "AUTH_TEST_DATABASE_URL", "AUTH_TEST_MIGRATION_DATABASE_URL"}
    assert shared <= set(AUTH_ACTIVE) and shared <= set(ROOT_ACTIVE)


def test_the_root_example_keeps_the_other_sections():
    assert {"JWT_ISSUER", "JWT_AUDIENCE", "GATEWAY_PORT", "CORS_ALLOWED_ORIGINS"} <= set(ROOT_ACTIVE)


# ------------------------------------------------------------------------------ retire-legacy-role
SCRIPT = ROOT / "setup" / "retire-legacy-role.sh"


def test_retire_script_only_ever_touches_auth_svc_and_never_drops():
    text = SCRIPT.read_text(encoding="utf-8")
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    assert "set -euo pipefail" in code
    assert "DROP" not in code.upper().replace("DROPPED", "")        # NOLOGIN, so it can be reversed
    assert "ALTER ROLE $LEGACY NOLOGIN" in code and 'LEGACY="auth_svc"' in code
    assert "REVOKE CONNECT ON DATABASE" in code
    # the only role it ever alters or revokes from is the legacy one
    for line in code.splitlines():
        if "ALTER ROLE" in line or "REVOKE" in line:
            assert "$LEGACY" in line, line
    assert "pg_shdepend" in code and "--plan" in code
    assert "auth_migrator auth_app" in code                          # replacements must exist first
    assert "ALTER ROLE auth_migrator" not in code and "ALTER ROLE auth_app" not in code


def test_retire_script_documents_the_undo():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "ALTER ROLE $LEGACY LOGIN" in text and "GRANT CONNECT ON DATABASE" in text


def find_bash():
    for candidate in ("C:/Program Files/Git/bin/bash.exe", "/bin/bash", "/usr/bin/bash"):
        if Path(candidate).exists():
            return candidate
    found = shutil.which("bash")
    return found if found and "system32" not in found.lower() else None


@pytest.mark.skipif(not find_bash(), reason="bash is required")
def test_retire_script_syntax_and_option_checking():
    bash = find_bash()
    assert subprocess.run([bash, "-n", str(SCRIPT)], capture_output=True).returncode == 0
    r = subprocess.run([bash, str(SCRIPT), "some-container", "--bogus"], capture_output=True, text=True, timeout=30)
    assert r.returncode == 2 and "unknown option" in r.stderr          # rejected before any docker call
    r = subprocess.run([bash, str(SCRIPT)], capture_output=True, text=True, timeout=30)
    assert r.returncode != 0 and "container name" in r.stderr


def test_the_makefile_exposes_both_targets():
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert re.search(r"^retire-legacy-role:\n\tbash setup/retire-legacy-role\.sh", text, re.M)
    assert re.search(r"^retire-legacy-role-plan:\n\tbash setup/retire-legacy-role\.sh .* --plan", text, re.M)
