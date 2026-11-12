"""Which database login Alembic uses. Kept out of migrations/env.py so it can be unit-tested."""
from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlsplit

# Logins that must NOT be the service's runtime connection: the legacy single role, and the schema owner.
NON_RUNTIME_ROLES = frozenset({"auth_svc", "auth_migrator"})


def resolve_migration_url(env: Mapping[str, str]) -> str:
    """The schema-owner URL, or a clear failure. There is deliberately NO fallback to AUTH_DATABASE_URL:
    that is the runtime role, which cannot (and must not) run DDL. Silently migrating with it would either
    fail confusingly or, on a single-role setup, hide that the role split was never applied."""
    url = env.get("AUTH_MIGRATION_DATABASE_URL")
    if url:
        return url
    hint = " (AUTH_DATABASE_URL is set, but that is the runtime role and is not used for migrations)" \
        if env.get("AUTH_DATABASE_URL") else ""
    raise RuntimeError(
        "AUTH_MIGRATION_DATABASE_URL is not set. Migrations run as the schema-owner role (auth_migrator); "
        f"set AUTH_MIGRATION_DATABASE_URL and retry{hint}.")


def url_username(url: str) -> str | None:
    """The login name in a SQLAlchemy/asyncpg URL (``postgresql+asyncpg://user:pw@host/db``)."""
    try:
        return urlsplit(url).username
    except ValueError:
        return None


def runtime_role_problem(runtime_url: str) -> str | None:
    """A message if the runtime connection uses a role it should not (None when it uses auth_app or anything else)."""
    user = url_username(runtime_url)
    if user in NON_RUNTIME_ROLES:
        return (f"AUTH_DATABASE_URL connects as '{user}'; the runtime must use the least-privilege role "
                "(auth_app). auth_migrator owns the schema and auth_svc is the retired single role")
    return None
