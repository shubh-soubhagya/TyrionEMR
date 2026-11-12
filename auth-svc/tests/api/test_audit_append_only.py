"""Audit-integrity item 1: auth_events is append-only for the runtime role; retention goes through
purge_auth_events(), which refuses to delete anything newer than 30 days and uses the database clock."""
import os
import subprocess
import sys

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.jobs.cleanup import run_cleanup_once
from tests.conftest import ROOT, TEST_DB_URL, TEST_MIGRATION_URL, must_be_denied, needs_split_roles, sql

pytestmark = pytest.mark.api


async def add_event(owner_engine, days_old, outcome="probe"):
    """An audit row dated by the DATABASE clock, inserted as the schema owner."""
    async with owner_engine.begin() as conn:
        await conn.execute(text("INSERT INTO auth_events (at, event, outcome) "
                                "VALUES (now() - make_interval(days => :d), 'probe', :o)"),
                           {"d": days_old, "o": outcome})


async def purge(engine, days):
    async with engine.begin() as conn:
        return (await conn.execute(text("SELECT purge_auth_events(:d)"), {"d": days})).scalar_one()


async def outcomes(app):
    return sorted(r[0] for r in await sql(app, "SELECT outcome FROM auth_events"))


# ------------------------------------------------------------------------------------- grants
@needs_split_roles
@pytest.mark.parametrize("statement", [
    "UPDATE auth_events SET outcome = 'tampered'",
    "DELETE FROM auth_events",
    "DELETE FROM auth_events WHERE false",
    "TRUNCATE auth_events",
])
async def test_the_runtime_role_cannot_rewrite_or_erase_the_audit_trail(as_app, statement):
    """Fails on the old code: the default privileges gave auth_app UPDATE and DELETE on every table."""
    await must_be_denied(as_app, statement)


@needs_split_roles
async def test_the_runtime_role_keeps_exactly_insert_and_select(as_app):
    async with as_app.connect() as conn:
        grants = {r[0] for r in await conn.execute(text(
            "SELECT privilege_type FROM information_schema.role_table_grants "
            "WHERE grantee = 'auth_app' AND table_name = 'auth_events'"))}
    assert grants == {"INSERT", "SELECT"}


@needs_split_roles
async def test_inserting_and_reading_audit_rows_still_works(as_app, app):
    async with as_app.begin() as conn:
        await conn.execute(text("INSERT INTO auth_events (at, event, outcome) VALUES (now(), 'probe', 'ok')"))
        assert (await conn.execute(text("SELECT count(*) FROM auth_events WHERE outcome = 'ok'"))).scalar() == 1


@needs_split_roles
async def test_other_tables_are_unaffected(as_app):
    """Only the audit trail is locked down: users and refresh_tokens keep DML."""
    async with as_app.connect() as conn:
        for table in ("users", "refresh_tokens"):
            privs = {r[0] for r in await conn.execute(text(
                "SELECT privilege_type FROM information_schema.role_table_grants "
                "WHERE grantee = 'auth_app' AND table_name = :t"), {"t": table})}
            assert {"SELECT", "INSERT", "UPDATE", "DELETE"} <= privs, (table, privs)


# ------------------------------------------------------------------------- the purge function
async def test_purge_deletes_only_rows_older_than_the_retention(app, as_app, as_owner):
    for days, name in ((400, "d400"), (366, "d366"), (364, "d364"), (1, "d1"), (0, "d0")):
        await add_event(as_owner, days, name)
    assert await purge(as_app, 365) == 2
    assert await outcomes(app) == ["d0", "d1", "d364"]


async def test_the_floor_is_exactly_30_days(app, as_app, as_owner):
    await add_event(as_owner, 31, "d31")
    await add_event(as_owner, 29, "d29")
    assert await purge(as_app, 30) == 1
    assert await outcomes(app) == ["d29"]


@pytest.mark.parametrize("days", [7, 0, -5, 29, None])
async def test_a_retention_below_30_days_raises_and_deletes_nothing(app, as_app, as_owner, days):
    await add_event(as_owner, 400, "ancient")
    await add_event(as_owner, 2, "recent")
    with pytest.raises(DBAPIError) as exc:
        await purge(as_app, days)
    assert "retention_days must be at least 30" in str(exc.value.orig)
    assert await outcomes(app) == ["ancient", "recent"]               # nothing was deleted


async def test_the_function_is_security_definer_with_a_pinned_search_path(as_owner):
    async with as_owner.connect() as conn:
        row = (await conn.execute(text(
            "SELECT p.prosecdef, p.proconfig, pg_get_userbyid(p.proowner), "
            "       pg_get_userbyid(c.relowner) "
            "FROM pg_proc p, pg_class c WHERE p.proname = 'purge_auth_events' AND c.relname = 'auth_events'"))).one()
        assert row[0] is True
        assert row[1] and any(c.replace(" ", "") == "search_path=pg_catalog,public" for c in row[1]), row[1]
        assert row[2] == row[3]                          # owned by whoever owns the table (auth_migrator)
        public_can_run = (await conn.execute(text(
            "SELECT EXISTS (SELECT 1 FROM pg_proc p, aclexplode(p.proacl) a "
            "WHERE p.proname = 'purge_auth_events' AND a.grantee = 0)"))).scalar()
        assert public_can_run is False                   # REVOKE ALL ... FROM PUBLIC


# ----------------------------------------------------------------------------- the cleanup job
async def test_the_cleanup_job_purges_old_events_through_the_function(app, as_owner):
    """In a two-role setup auth_app has no DELETE, so this only passes if the job uses the function."""
    await add_event(as_owner, 400, "old")
    await add_event(as_owner, 10, "recent")
    await run_cleanup_once(app.state.sessionmaker, app.state.settings, app.state.clock)
    assert await outcomes(app) == ["recent"]


async def test_the_caller_cannot_fake_the_clock_to_widen_the_purge(app, as_owner, clock):
    """Fails on the old code, which computed the cut-off from the (fakeable) application clock."""
    await add_event(as_owner, 5, "five-days-old")
    clock.advance(days=3650)                              # the app believes it is ten years later
    await run_cleanup_once(app.state.sessionmaker, app.state.settings, app.state.clock)
    assert await outcomes(app) == ["five-days-old"]


# ------------------------------------------------------------------------------- the migration
def alembic(*args):
    env = {**os.environ, "AUTH_DATABASE_URL": TEST_DB_URL, "AUTH_MIGRATION_DATABASE_URL": TEST_MIGRATION_URL or ""}
    return subprocess.run([sys.executable, "-m", "alembic", *args], cwd=ROOT, env=env, capture_output=True, text=True)


@needs_split_roles
async def test_downgrade_restores_the_old_grants_and_upgrade_locks_them_again(as_app, as_owner):
    try:
        assert alembic("downgrade", "0004").returncode == 0
        async with as_owner.connect() as conn:
            gone = await conn.execute(text("SELECT to_regprocedure('public.purge_auth_events(integer)')"))
            assert gone.scalar() is None
        async with as_app.connect() as conn:
            privs = {r[0] for r in await conn.execute(text(
                "SELECT privilege_type FROM information_schema.role_table_grants "
                "WHERE grantee = 'auth_app' AND table_name = 'auth_events'"))}
        assert privs == {"SELECT", "INSERT", "UPDATE", "DELETE"}          # the previous grants
    finally:
        assert alembic("upgrade", "head").returncode == 0
    await must_be_denied(as_app, "DELETE FROM auth_events")


def test_every_statement_naming_auth_app_is_guarded_by_a_role_check():
    """A database without an auth_app role (single-role setups) must still migrate. Roles are cluster-wide, so
    instead of dropping one we check that no GRANT/REVOKE for auth_app can run outside an IF EXISTS guard."""
    migration = ROOT / "migrations" / "versions" / "0005_auth_events_append_only.py"
    lines = migration.read_text(encoding="utf-8").splitlines()
    guarded = False
    seen = 0
    for line in lines:
        stripped = line.strip()
        if "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'auth_app')" in stripped:
            guarded = True
        elif stripped.startswith("END IF;"):
            guarded = False
        elif ("auth_app" in stripped and stripped.split()[:1] in (["GRANT"], ["REVOKE"])
              and "FROM PUBLIC" not in stripped):
            seen += 1
            assert guarded, f"unguarded statement naming auth_app: {stripped}"
    assert seen == 4                                     # revoke, grant, grant execute, downgrade grant
