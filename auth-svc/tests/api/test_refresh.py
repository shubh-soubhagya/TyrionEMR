import pytest

from tests.conftest import (
    GOOD_PASSWORD,
    client_for,
    rt_cookie,
    set_cookie_headers,
    sql,
    with_cookie,
)

pytestmark = pytest.mark.api
EMAIL = "dr.rao@nephrocare.demo"


async def signed_in(client, make_user):
    await make_user()
    r = await client.post("/auth/login", json={"email": EMAIL, "password": GOOD_PASSWORD})
    return rt_cookie(r), r.json()


async def refresh(client, raw, **headers):
    return await client.post("/auth/refresh", headers={**with_cookie(raw), **headers})


def code(r):
    return r.json()["error"]["code"]


async def test_refresh_rotates_the_token(client, make_user, app):
    rt1, _ = await signed_in(client, make_user)
    r = await refresh(client, rt1)
    assert r.status_code == 200 and r.json()["access_token"] and r.json()["user"]["email"] == EMAIL
    rt2 = rt_cookie(r)
    assert rt2 and rt2 != rt1
    assert r.headers["cache-control"] == "no-store"
    rows = await sql(app, "SELECT revoked_reason, replaced_by_id IS NOT NULL FROM refresh_tokens "
                          "ORDER BY created_at, revoked_at NULLS LAST")
    assert sorted(rows, key=lambda x: x[0] is None) == [("rotated", True), (None, False)]


async def test_new_token_works_and_old_family_chain_is_one_family(client, make_user, app):
    rt1, _ = await signed_in(client, make_user)
    rt2 = rt_cookie(await refresh(client, rt1))
    assert (await refresh(client, rt2)).status_code == 200
    assert (await sql(app, "SELECT count(DISTINCT family_id) FROM refresh_tokens"))[0][0] == 1


async def test_missing_cookie_is_401_refresh_missing(client):
    r = await client.post("/auth/refresh")
    assert r.status_code == 401 and code(r) == "REFRESH_MISSING"


async def test_unknown_token_is_invalid_and_cookie_is_cleared(client, make_user):
    await make_user()
    r = await refresh(client, "x" * 43)
    assert r.status_code == 401 and code(r) == "REFRESH_INVALID"
    (c,) = set_cookie_headers(r)
    assert "Max-Age=0" in c and "Path=/api/auth" in c


async def test_idle_expiry(client, make_user, clock):
    rt, _ = await signed_in(client, make_user)
    clock.advance(days=7, seconds=1)
    r = await refresh(client, rt)
    assert r.status_code == 401 and code(r) == "REFRESH_EXPIRED" and "Max-Age=0" in set_cookie_headers(r)[0]


async def test_absolute_session_cap(make_app, make_user, clock):
    app = await make_app(session_max_days=10)
    import uuid

    from app.models import User
    async with app.state.sessionmaker() as s, s.begin():
        s.add(User(id=uuid.uuid4(), email=EMAIL, full_name="Dr. Rao", role="clinician",
                   password_hash=await app.state.hasher.hash(GOOD_PASSWORD),
                   created_at=clock(), updated_at=clock()))
    async with client_for(app) as c:
        rt = rt_cookie(await c.post("/auth/login", json={"email": EMAIL, "password": GOOD_PASSWORD}))
        clock.advance(days=6)                       # within idle window of 7 d
        r = await refresh(c, rt)
        assert r.status_code == 200
        rt = rt_cookie(r)
        clock.advance(days=5)                       # day 11: idle window not over, absolute cap (10 d) is
        r = await refresh(c, rt)
    assert r.status_code == 401 and code(r) == "REFRESH_EXPIRED"


async def test_reuse_outside_grace_revokes_whole_family(client, make_user, app, clock):
    rt1, _ = await signed_in(client, make_user)
    rt2 = rt_cookie(await refresh(client, rt1))
    clock.advance(seconds=11)                       # past the 10 s race window
    r = await refresh(client, rt1)                  # the thief replays the old token
    assert r.status_code == 401 and code(r) == "REFRESH_REUSED"
    assert "Max-Age=0" in set_cookie_headers(r)[0]
    assert (await sql(app, "SELECT count(*) FROM refresh_tokens WHERE revoked_at IS NULL"))[0][0] == 0
    # the legitimate holder of rt2 is now signed out too
    assert (await refresh(client, rt2)).status_code == 401


async def test_revocation_persists_after_the_error_response(client, make_user, app, clock):
    """Regression for LLD 19.3: the family revocation must COMMIT even though the response is an error.
    Raising inside the transaction block would roll it back and leave the stolen chain alive."""
    rt1, _ = await signed_in(client, make_user)
    rt2 = rt_cookie(await refresh(client, rt1))
    clock.advance(seconds=11)
    assert code(await refresh(client, rt1)) == "REFRESH_REUSED"
    rows = await sql(app, "SELECT revoked_reason FROM refresh_tokens ORDER BY created_at")
    assert [r[0] for r in rows] == ["rotated", "reuse_detected"]    # the live token was revoked and it stuck
    again = await refresh(client, rt2)   # already revoked as reuse_detected: just an ended session
    assert again.status_code == 401 and code(again) == "REFRESH_INVALID"


async def test_reuse_inside_grace_is_409_and_changes_nothing(client, make_user, app, clock):
    rt1, _ = await signed_in(client, make_user)
    r2 = await refresh(client, rt1)
    rt2 = rt_cookie(r2)
    clock.advance(seconds=3)
    r = await refresh(client, rt1)                  # second tab with the stale cookie
    assert r.status_code == 409 and code(r) == "REFRESH_RACE"
    assert set_cookie_headers(r) == []              # cookie untouched: the tab retries with the new one
    assert "access_token" not in r.text             # the window never issues a token
    assert (await sql(app, "SELECT count(*) FROM refresh_tokens WHERE revoked_at IS NULL"))[0][0] == 1
    assert (await refresh(client, rt2)).status_code == 200


async def test_grace_boundary_is_ten_seconds(client, make_user, clock):
    rt1, _ = await signed_in(client, make_user)
    await refresh(client, rt1)
    clock.advance(seconds=10)
    assert code(await refresh(client, rt1)) == "REFRESH_RACE"


async def test_inactive_user_revokes_family(client, make_user, app):
    rt, _ = await signed_in(client, make_user)
    await sql(app, "SELECT 1")
    async with app.state.sessionmaker() as s, s.begin():
        from sqlalchemy import text
        await s.execute(text("UPDATE users SET is_active = false"))
    r = await refresh(client, rt)
    assert r.status_code == 401 and code(r) == "REFRESH_INVALID"
    assert (await sql(app, "SELECT revoked_reason FROM refresh_tokens"))[0][0] == "user_inactive"


async def test_untrusted_origin_is_403_and_trusted_passes(client, make_user):
    rt, _ = await signed_in(client, make_user)
    bad = await refresh(client, rt, origin="https://evil.example")
    assert bad.status_code == 403 and code(bad) == "ORIGIN_NOT_ALLOWED"
    assert set_cookie_headers(bad) == []
    ok = await refresh(client, rt, origin="http://localhost:4200")
    assert ok.status_code == 200


async def test_logout_then_refresh_with_old_cookie_is_invalid_not_reuse(client, make_user, app, caplog):
    import logging

    from app.core.logging import JsonFormatter

    rt, _ = await signed_in(client, make_user)
    assert (await client.post("/auth/logout", headers=with_cookie(rt))).status_code == 204
    before = await sql(app, "SELECT id, revoked_reason, revoked_at FROM refresh_tokens ORDER BY id")

    caplog.set_level(logging.DEBUG)
    r = await refresh(client, rt)

    assert r.status_code == 401 and code(r) == "REFRESH_INVALID"
    (c,) = set_cookie_headers(r)
    assert "Max-Age=0" in c
    assert await sql(app, "SELECT id, revoked_reason, revoked_at FROM refresh_tokens ORDER BY id") == before
    logs = "\n".join(JsonFormatter("auth-svc").format(rec) for rec in caplog.records)
    assert "auth.refresh.reuse_detected" not in logs
    assert '"event":"auth.refresh.failure"' in logs and '"reason":"invalid"' in logs
    assert not [rec for rec in caplog.records if rec.levelno >= logging.WARNING]


async def test_replaying_a_reuse_revoked_token_does_not_log_reuse_again(client, make_user, clock, caplog):
    import logging

    rt1, _ = await signed_in(client, make_user)
    rt2 = rt_cookie(await refresh(client, rt1))
    clock.advance(seconds=11)
    assert code(await refresh(client, rt1)) == "REFRESH_REUSED"     # the one real theft event
    caplog.clear()
    caplog.set_level(logging.DEBUG)
    r = await refresh(client, rt2)                                  # revoked_reason='reuse_detected'
    assert r.status_code == 401 and code(r) == "REFRESH_INVALID"
    assert not [rec for rec in caplog.records if rec.getMessage() == "auth.refresh.reuse_detected"]
