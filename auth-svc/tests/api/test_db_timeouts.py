"""Item 6: database timeouts turn hangs into fast 503 SERVICE_BUSY, never a 500 or a stuck request."""
import asyncio

import pytest
from sqlalchemy import text

from app.services.token_service import TokenService
from tests.conftest import GOOD_PASSWORD, client_for, rt_cookie, with_cookie

pytestmark = pytest.mark.api
EMAIL = "dr.rao@nephrocare.demo"


async def test_server_side_timeouts_are_set_on_every_connection(app):
    async with app.state.sessionmaker() as s:
        values = {name: (await s.execute(text(f"SHOW {name}"))).scalar() for name in
                  ("statement_timeout", "lock_timeout", "idle_in_transaction_session_timeout")}
    assert values == {"statement_timeout": "5s", "lock_timeout": "2s", "idle_in_transaction_session_timeout": "10s"}


async def test_locked_refresh_token_row_gives_503_in_about_two_seconds(client, make_user, app):
    await make_user()
    login = await client.post("/auth/login", json={"email": EMAIL, "password": GOOD_PASSWORD})
    raw = rt_cookie(login)
    token_hash = TokenService.hash_refresh(raw)

    loop = asyncio.get_running_loop()
    async with app.state.engine.connect() as holder:        # another connection keeps the row locked
        await holder.execute(text("SELECT 1 FROM refresh_tokens WHERE token_hash = :h FOR UPDATE"),
                             {"h": token_hash})
        start = loop.time()
        r = await client.post("/auth/refresh", headers=with_cookie(raw))
        elapsed = loop.time() - start
        await holder.rollback()

    assert r.status_code == 503 and r.json()["error"]["code"] == "SERVICE_BUSY"
    assert r.headers["retry-after"] == "1"
    assert 1.5 <= elapsed < 4.0, f"expected ~2 s lock timeout, took {elapsed:.2f}s"
    # nothing was consumed: once the lock is gone the same cookie still refreshes
    assert (await client.post("/auth/refresh", headers=with_cookie(raw))).status_code == 200


async def test_statement_timeout_gives_503(make_app):
    app = await make_app(db_statement_timeout_ms=300)

    @app.get("/_slow")
    async def slow():
        async with app.state.sessionmaker() as s:
            await s.execute(text("SELECT pg_sleep(3)"))

    async with client_for(app) as c:
        r = await c.get("/_slow")
    assert r.status_code == 503 and r.json()["error"]["code"] == "SERVICE_BUSY"


async def test_other_database_errors_are_a_500_envelope_without_sql_or_details(make_app):
    app = await make_app()

    @app.get("/_broken")
    async def broken():
        async with app.state.sessionmaker() as s:
            await s.execute(text("SELECT * FROM table_that_does_not_exist_zzz"))

    async with client_for(app) as c:
        r = await c.get("/_broken")
    assert r.status_code == 500 and r.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "table_that_does_not_exist_zzz" not in r.text and "SELECT" not in r.text
