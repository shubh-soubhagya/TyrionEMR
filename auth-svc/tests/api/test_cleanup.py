import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text

from app.jobs.cleanup import CLEANUP_LOCK_ID, run_cleanup_once
from tests.conftest import sql

pytestmark = pytest.mark.api


async def add_token(app, user_id, expires_in_days, revoked=False):
    now = app.state.clock()
    exp = now + timedelta(days=expires_in_days)
    async with app.state.sessionmaker() as s, s.begin():
        await s.execute(text(
            "INSERT INTO refresh_tokens (user_id,family_id,token_hash,expires_at,family_expires_at,"
            "revoked_at,revoked_reason) VALUES (:u,gen_random_uuid(),:h,:e,:e,:ra,:rr)"),
            {"u": user_id, "h": uuid.uuid4().hex + uuid.uuid4().hex, "e": exp,
             "ra": now if revoked else None, "rr": "logout" if revoked else None})


async def test_only_tokens_expired_beyond_the_retention_tail_are_deleted(app, make_user):
    user = await make_user()
    await add_token(app, user.id, expires_in_days=-8)                 # expired 8 days ago -> purge
    await add_token(app, user.id, expires_in_days=-8, revoked=True)   # same, revoked      -> purge
    await add_token(app, user.id, expires_in_days=-3)                 # inside 7-day tail  -> keep
    await add_token(app, user.id, expires_in_days=5)                  # still valid        -> keep
    n = await run_cleanup_once(app.state.sessionmaker, app.state.settings, app.state.clock)
    assert n == 2
    assert (await sql(app, "SELECT count(*) FROM refresh_tokens"))[0][0] == 2


async def test_cleanup_is_skipped_when_another_replica_holds_the_lock(app, make_user):
    user = await make_user()
    await add_token(app, user.id, expires_in_days=-30)
    async with app.state.sessionmaker() as other, other.begin():
        await other.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": CLEANUP_LOCK_ID})
        n = await run_cleanup_once(app.state.sessionmaker, app.state.settings, app.state.clock)
    assert n is None
    assert (await sql(app, "SELECT count(*) FROM refresh_tokens"))[0][0] == 1
