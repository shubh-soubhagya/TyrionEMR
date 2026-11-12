"""`alembic upgrade head` on an empty database must produce exactly the schema in LLD 15.2."""
import pytest

from tests.conftest import sql

pytestmark = pytest.mark.api

EXPECTED_COLUMNS = {
    "users": {
        "id": ("uuid", "NO"), "email": ("USER-DEFINED", "NO"), "password_hash": ("text", "NO"),
        "full_name": ("text", "NO"), "role": ("text", "NO"), "is_active": ("boolean", "NO"),
        "failed_login_count": ("integer", "NO"), "locked_until": ("timestamp with time zone", "YES"),
        "last_login_at": ("timestamp with time zone", "YES"),
        "last_failed_at": ("timestamp with time zone", "YES"),
        "created_at": ("timestamp with time zone", "NO"), "updated_at": ("timestamp with time zone", "NO"),
    },
    "refresh_tokens": {
        "id": ("uuid", "NO"), "user_id": ("uuid", "NO"), "family_id": ("uuid", "NO"),
        "token_hash": ("text", "NO"), "expires_at": ("timestamp with time zone", "NO"),
        "family_expires_at": ("timestamp with time zone", "NO"),
        "revoked_at": ("timestamp with time zone", "YES"), "revoked_reason": ("text", "YES"),
        "replaced_by_id": ("uuid", "YES"), "user_agent": ("text", "YES"),
        "created_at": ("timestamp with time zone", "NO"),
    },
}
EXPECTED_CONSTRAINTS = {
    "uq_users_email", "ck_users_email_len", "ck_users_full_name_len", "ck_users_role",
    "ck_users_failed_count", "ck_users_hash_format", "uq_refresh_tokens_hash", "ck_rt_hash_len",
    "ck_rt_expiry_order", "ck_rt_revoked_reason", "ck_rt_revoked_consistency", "ck_rt_user_agent_len",
}
EXPECTED_INDEXES = {"ix_rt_family_active", "ix_rt_user_id", "ix_rt_expires_at"}


async def test_columns_match(app):
    rows = await sql(app, "SELECT table_name, column_name, data_type, is_nullable FROM information_schema.columns "
                          "WHERE table_schema='public' AND table_name IN ('users','refresh_tokens')")
    actual: dict[str, dict] = {}
    for t, c, d, n in rows:
        actual.setdefault(t, {})[c] = (d, n)
    assert actual == EXPECTED_COLUMNS


async def test_named_constraints_and_indexes_match(app):
    cons = {r[0] for r in await sql(app, "SELECT conname FROM pg_constraint WHERE conname ~ '^(uq|ck)_'")}
    assert cons == EXPECTED_CONSTRAINTS
    idx = {r[0] for r in await sql(app, "SELECT indexname FROM pg_indexes WHERE schemaname='public' "
                                         "AND indexname LIKE 'ix_%'")}
    assert idx == EXPECTED_INDEXES
    (pred,) = (await sql(app, "SELECT indexdef FROM pg_indexes WHERE indexname='ix_rt_family_active'"))[0]
    assert "WHERE (revoked_at IS NULL)" in pred


async def test_database_enforces_the_rules_even_if_the_app_does_not(app):
    from sqlalchemy.exc import DBAPIError
    bad = [
        "INSERT INTO users (email,password_hash,full_name,role) VALUES ('a@b.c','plaintext','Dr X','clinician')",
        "INSERT INTO users (email,password_hash,full_name,role) VALUES ('a@b.c','$argon2id$x','Dr X','admin')",
    ]
    for stmt in bad:
        with pytest.raises(DBAPIError):
            async with app.state.sessionmaker() as s, s.begin():
                from sqlalchemy import text
                await s.execute(text(stmt))
