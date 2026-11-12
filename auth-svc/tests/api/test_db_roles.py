"""Item 5: least-privilege roles. Runs only when the runtime and migration URLs are different roles
(AUTH_TEST_DATABASE_URL = auth_app, AUTH_TEST_MIGRATION_DATABASE_URL = auth_migrator)."""
import pytest
from sqlalchemy import text

from tests.conftest import client_for, must_be_denied, needs_split_roles

pytestmark = pytest.mark.api

@needs_split_roles
@pytest.mark.parametrize("statement", [
    "DROP TABLE users",
    "DROP TABLE refresh_tokens",
    "DROP TABLE auth_events",
    "CREATE TABLE x ()",
    "ALTER TABLE users ADD COLUMN zz integer",
    "TRUNCATE users",
    "CREATE INDEX zz_idx ON users (full_name)",
    "DROP SCHEMA public CASCADE",
    "CREATE SCHEMA zz",
    "DROP EXTENSION citext",
])
async def test_the_runtime_role_cannot_change_the_schema(as_app, statement):
    await must_be_denied(as_app, statement)


@needs_split_roles
async def test_the_runtime_role_can_read_and_write_rows(as_app):
    async with as_app.begin() as conn:
        await conn.execute(text(
            "INSERT INTO users (email, password_hash, full_name) "
            "VALUES ('role.test@x.test', '$argon2id$x', 'Role Test')"))
        assert (await conn.execute(text("SELECT count(*) FROM users WHERE email='role.test@x.test'"))).scalar() == 1
        await conn.execute(text("UPDATE users SET full_name='Renamed' WHERE email='role.test@x.test'"))
        await conn.execute(text("DELETE FROM users WHERE email='role.test@x.test'"))
        assert (await conn.execute(text("SELECT count(*) FROM alembic_version"))).scalar() == 1


@needs_split_roles
async def test_the_migrator_owns_everything_and_the_runtime_role_owns_nothing(as_owner):
    async with as_owner.connect() as conn:
        owners = {r[0]: r[1] for r in await conn.execute(text(
            "SELECT tablename, tableowner FROM pg_tables WHERE schemaname='public'"))}
        assert owners and set(owners.values()) == {"auth_migrator"}, owners
        schema_owner = (await conn.execute(text(
            "SELECT nspowner::regrole::text FROM pg_namespace WHERE nspname='public'"))).scalar()
        assert schema_owner == "auth_migrator"
        flags = (await conn.execute(text(
            "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication "
            "FROM pg_roles WHERE rolname='auth_app'"))).one()
        assert tuple(flags) == (False, False, False, False)
        owned_by_app = (await conn.execute(text(
            "SELECT count(*) FROM pg_class c JOIN pg_roles r ON r.oid = c.relowner "
            "WHERE r.rolname='auth_app'"))).scalar()
        assert owned_by_app == 0


@needs_split_roles
async def test_tables_created_later_by_the_migrator_are_usable_by_the_runtime_role(as_owner, as_app):
    """ALTER DEFAULT PRIVILEGES: a future migration's tables need no extra GRANT."""
    async with as_owner.begin() as conn:
        await conn.execute(text("CREATE TABLE zz_future_table (id integer)"))
    try:
        async with as_app.begin() as conn:
            await conn.execute(text("INSERT INTO zz_future_table VALUES (1)"))
            assert (await conn.execute(text("SELECT count(*) FROM zz_future_table"))).scalar() == 1
        await must_be_denied(as_app, "DROP TABLE zz_future_table")
    finally:
        async with as_owner.begin() as conn:
            await conn.execute(text("DROP TABLE IF EXISTS zz_future_table"))


@needs_split_roles
async def test_the_migrator_can_do_ddl(as_owner):
    async with as_owner.begin() as conn:
        await conn.execute(text("CREATE TABLE zz_ddl_probe (id integer)"))
        await conn.execute(text("DROP TABLE zz_ddl_probe"))


@needs_split_roles
async def test_the_service_works_end_to_end_as_the_runtime_role(client, make_user):
    """The whole login/refresh/password/audit flow runs with DML-only rights."""
    await make_user()
    r = await client.post("/auth/login", json={"email": "dr.rao@nephrocare.demo", "password": "Kidney2026care"})
    assert r.status_code == 200
    assert (await client.get("/ready")).status_code == 200


@needs_split_roles
async def test_ready_does_not_need_ddl(make_app):
    app = await make_app()
    async with client_for(app) as c:
        assert (await c.get("/ready")).json()["migrations"] == "head"
