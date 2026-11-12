"""Item 13: durable auth audit trail."""
import asyncio
from datetime import timedelta

import pytest

from app.jobs.cleanup import run_cleanup_once
from tests.conftest import GOOD_PASSWORD, rt_cookie, sql, with_cookie

pytestmark = pytest.mark.api
EMAIL = "dr.rao@nephrocare.demo"
ORIGIN = {"origin": "http://localhost:4200"}
COLUMNS = ["id", "at", "event", "outcome", "user_id", "family_id", "request_id", "ip", "user_agent"]


async def events(app):
    rows = await sql(app, "SELECT event, outcome, user_id, family_id, request_id, host(ip), user_agent, at "
                          "FROM auth_events ORDER BY at, event, outcome")
    names = ["event", "outcome", "user_id", "family_id", "request_id", "ip", "user_agent", "at"]
    return [dict(zip(names, r, strict=True)) for r in rows]


def of(evs, event, outcome=None):
    return [e for e in evs if e["event"] == event and (outcome is None or e["outcome"] == outcome)]


async def test_signup_is_recorded_with_all_fields(client, app):
    r = await client.post("/auth/signup", json={"full_name": "Dr. New", "email": "new.person@nephrocare.demo",
                                                "password": "Pass-Word-2026x"}, headers={"user-agent": "pytest-ua/1.0"})
    assert r.status_code == 201
    (e,) = of(await events(app), "signup", "success")
    assert str(e["user_id"]) == r.json()["user"]["id"] and e["family_id"] is not None
    assert e["ip"] == "127.0.0.1" and e["user_agent"] == "pytest-ua/1.0"
    assert e["request_id"] == r.headers["x-request-id"] and e["at"] == app.state.clock()


async def test_signup_rejections_are_recorded_without_the_email(client, app):
    body = {"full_name": "Dr. New", "email": "new.person@nephrocare.demo", "password": "Pass-Word-2026x"}
    await client.post("/auth/signup", json=body)
    await client.post("/auth/signup", json=body)                                   # email taken
    await client.post("/auth/signup", json={**body, "email": "other@nephrocare.demo", "password": "short"})
    evs = await events(app)
    assert len(of(evs, "signup", "email_taken")) == 1 and len(of(evs, "signup", "policy")) == 1


async def test_login_success_failure_unknown_and_lockout(client, make_user, app):
    user = await make_user()
    login = lambda pw, email=EMAIL: client.post("/auth/login", json={"email": email, "password": pw})  # noqa: E731
    await login(GOOD_PASSWORD)
    await login("nobody-Pass1234", email="nobody@nephrocare.demo")
    for _ in range(5):
        await login("WrongPassword99")
    await login(GOOD_PASSWORD)                                                    # locked now
    evs = await events(app)

    (ok,) = of(evs, "login", "success")
    assert ok["user_id"] == user.id and ok["family_id"] is not None
    (unknown,) = of(evs, "login", "unknown_user")
    assert unknown["user_id"] is None                                            # no user, and never an email
    assert len(of(evs, "login", "bad_password")) == 5
    assert len(of(evs, "lockout", "locked")) == 1                                 # exactly one flip
    assert len(of(evs, "login", "locked")) == 1
    assert all(e["request_id"] and e["ip"] == "127.0.0.1" for e in evs)


async def test_parallel_failures_record_one_lockout(client, make_user, app):
    await make_user()
    await asyncio.gather(*[client.post("/auth/login", json={"email": EMAIL, "password": f"WrongGuess{i:02d}x"})
                           for i in range(12)])
    evs = await events(app)
    assert len(of(evs, "lockout")) == 1
    assert len(of(evs, "login", "bad_password")) <= 5


async def test_disabled_account_is_recorded(client, make_user, app):
    await make_user(active=False)
    await client.post("/auth/login", json={"email": EMAIL, "password": GOOD_PASSWORD})
    assert len(of(await events(app), "login", "disabled")) == 1


async def test_refresh_reuse_logout_and_password_change(client, make_user, app, clock):
    user = await make_user()
    login = await client.post("/auth/login", json={"email": EMAIL, "password": GOOD_PASSWORD})
    rt1 = rt_cookie(login)
    rt2 = rt_cookie(await client.post("/auth/refresh", headers=with_cookie(rt1)))
    clock.advance(seconds=11)
    await client.post("/auth/refresh", headers=with_cookie(rt1))                  # replay -> reuse_detected
    (reuse,) = of(await events(app), "refresh", "reuse_detected")
    assert reuse["user_id"] == user.id and reuse["family_id"] is not None

    fresh = await client.post("/auth/login", json={"email": EMAIL, "password": GOOD_PASSWORD})
    rt3 = rt_cookie(fresh)
    await client.post("/auth/logout", headers=with_cookie(rt3))
    (out,) = of(await events(app), "logout", "success")
    assert out["user_id"] == user.id

    again = await client.post("/auth/login", json={"email": EMAIL, "password": GOOD_PASSWORD})
    await client.post("/auth/password", json={"current_password": GOOD_PASSWORD, "new_password": "Glomerular2027!x"},
                      headers={"authorization": "Bearer " + again.json()["access_token"], **ORIGIN,
                               **with_cookie(rt_cookie(again))})
    (pw,) = of(await events(app), "password_change", "success")
    assert pw["user_id"] == user.id and pw["family_id"] is not None
    assert rt2  # silence unused


async def test_user_agent_is_truncated_to_256(client, make_user, app):
    await make_user()
    await client.post("/auth/login", json={"email": EMAIL, "password": GOOD_PASSWORD},
                      headers={"user-agent": "x" * 600})
    (e,) = of(await events(app), "login", "success")
    assert len(e["user_agent"]) == 256


async def test_the_event_commits_with_the_change_it_records(client, make_user, app, monkeypatch):
    """If the change fails, its event must not exist (same transaction)."""
    await make_user()
    users = app.state.auth_service._users

    async def boom(*a, **k):
        raise RuntimeError("simulated failure after the event was added")

    monkeypatch.setattr(users, "register_success", boom)
    r = await client.post("/auth/login", json={"email": EMAIL, "password": GOOD_PASSWORD})
    assert r.status_code == 500
    assert of(await events(app), "login", "success") == []
    assert (await sql(app, "SELECT count(*) FROM refresh_tokens"))[0][0] == 0


async def test_there_are_no_pii_columns_and_no_pii_values(client, make_user, app):
    cols = [r[0] for r in await sql(app, "SELECT column_name FROM information_schema.columns "
                                         "WHERE table_name='auth_events' ORDER BY ordinal_position")]
    assert sorted(cols) == sorted(COLUMNS)
    assert not {"email", "password", "token", "cookie", "token_hash"} & set(cols)

    await make_user()
    await client.post("/auth/login", json={"email": EMAIL, "password": GOOD_PASSWORD})
    await client.post("/auth/login", json={"email": "ghost@nephrocare.demo", "password": "Secret-Pass-9999"})
    dump = " ".join(str(v) for row in await sql(app, "SELECT * FROM auth_events") for v in row)
    for needle in (EMAIL, "dr.rao", "ghost@", "nephrocare", GOOD_PASSWORD, "Secret-Pass-9999"):
        assert needle not in dump, f"audit row contains {needle}"


async def test_retention_purges_old_events_only(client, make_user, app, clock):
    await make_user()
    await client.post("/auth/login", json={"email": EMAIL, "password": GOOD_PASSWORD})
    clock.advance(days=366)
    await client.post("/auth/login", json={"email": EMAIL, "password": "WrongPassword99"})   # a recent event
    assert len(await events(app)) == 2
    await run_cleanup_once(app.state.sessionmaker, app.state.settings, app.state.clock)
    evs = await events(app)
    assert len(evs) == 1 and evs[0]["outcome"] == "bad_password"
    assert evs[0]["at"] > app.state.clock() - timedelta(days=1)
