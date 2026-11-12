"""Item 1/1b: attempt reservation closes the parallel-guess lockout bypass; the counter decays."""
import asyncio

import pytest
from sqlalchemy import text

from tests.conftest import GOOD_PASSWORD, client_for, sql

pytestmark = pytest.mark.api
EMAIL = "dr.rao@nephrocare.demo"


def spy_verifications(app, monkeypatch):
    """Counts REAL password verifications (dummy verifies for unknown emails are not counted)."""
    calls: list[str] = []
    original = app.state.hasher.verify

    async def spy(encoded, password):
        calls.append(password)
        return await original(encoded, password)

    monkeypatch.setattr(app.state.hasher, "verify", spy)
    return calls


async def post(client, password):
    return await client.post("/auth/login", json={"email": EMAIL, "password": password})


async def test_twenty_parallel_wrong_guesses_try_at_most_five_passwords(client, make_user, app, monkeypatch):
    await make_user()
    verifications = spy_verifications(app, monkeypatch)

    results = await asyncio.gather(*[post(client, f"WrongGuess{i:02d}x") for i in range(20)])

    assert len(verifications) <= 5, f"{len(verifications)} guesses reached argon2; the lock allows 5"
    statuses = sorted(r.status_code for r in results)
    assert statuses.count(401) <= 5 and set(statuses) <= {401, 429}
    assert statuses.count(429) >= 15
    (locked_until, count) = (await sql(app, "SELECT locked_until, failed_login_count FROM users"))[0]
    assert locked_until is not None and locked_until > app.state.clock()
    assert count == 0                                    # the lock resets the counter


async def test_correct_password_cannot_succeed_after_the_account_locked(client, make_user, app, monkeypatch):
    """The correct request is slowed so the other nine lock the account while it is still verifying.
    On the success path the lock is re-checked under a row lock, so it must answer 429, not 200."""
    await make_user()
    original = app.state.hasher.verify

    async def slow_if_correct(encoded, password):
        ok = await original(encoded, password)
        if ok:
            await asyncio.sleep(0.5)                     # others lock the account in the meantime
        return ok

    monkeypatch.setattr(app.state.hasher, "verify", slow_if_correct)

    results = await asyncio.gather(
        post(client, GOOD_PASSWORD), *[post(client, f"WrongGuess{i:02d}x") for i in range(9)])

    correct = results[0]
    assert correct.status_code == 429 and correct.json()["error"]["code"] == "ACCOUNT_LOCKED"
    assert "set-cookie" not in correct.headers and "access_token" not in correct.text
    (locked_until, last_login) = (await sql(app, "SELECT locked_until, last_login_at FROM users"))[0]
    assert locked_until is not None and last_login is None          # no session was started
    assert (await sql(app, "SELECT count(*) FROM refresh_tokens"))[0][0] == 0


async def test_burst_never_succeeds_after_the_lock_was_set(client, make_user, app, monkeypatch):
    """Randomised interleavings: whenever the correct password wins, it did so BEFORE any lock-out."""
    await make_user()
    users = app.state.auth_service._users
    events: list[str] = []
    orig_lock, orig_success = users.lock_out, users.register_success

    async def lock_out(*a, **k):
        res = await orig_lock(*a, **k)
        events.append("lock")
        return res

    async def register_success(*a, **k):
        events.append("success")
        return await orig_success(*a, **k)

    monkeypatch.setattr(users, "lock_out", lock_out)
    monkeypatch.setattr(users, "register_success", register_success)

    for round_no in range(6):
        events.clear()
        await sql(app, "SELECT 1")
        async with app.state.sessionmaker() as s, s.begin():
            await s.execute(text("UPDATE users SET failed_login_count=0, locked_until=NULL, last_failed_at=NULL"))
        passwords = [f"WrongGuess{i:02d}x" for i in range(9)]
        passwords.insert(round_no % 10, GOOD_PASSWORD)
        results = await asyncio.gather(*[post(client, p) for p in passwords])
        winners = [r for r in results if r.status_code == 200]
        assert len(winners) <= 1
        if winners:
            assert "success" in events and "lock" in events
            assert events.index("success") < events.index("lock"), f"round {round_no}: success after lock {events}"
        else:
            assert "success" not in events


async def test_service_busy_gives_the_attempt_back(make_app, make_user):
    app = await make_app(argon2_max_concurrency=1, argon2_queue_timeout_s=0.2)
    import uuid

    from app.models import User
    async with app.state.sessionmaker() as s, s.begin():
        s.add(User(id=uuid.uuid4(), email=EMAIL, full_name="Dr. Rao", role="clinician",
                   password_hash=await app.state.hasher.hash(GOOD_PASSWORD),
                   created_at=app.state.clock(), updated_at=app.state.clock()))
    await app.state.hasher._sem.acquire()               # saturate the hash pool
    try:
        async with client_for(app) as c:
            for _ in range(8):                           # more than the 5-attempt budget
                r = await post(c, "WrongGuess01x")
                assert r.status_code == 503
    finally:
        app.state.hasher._sem.release()
    assert (await sql(app, "SELECT failed_login_count, locked_until FROM users"))[0] == (0, None)


# --------------------------------------------------------------------------------- 1b decay
async def test_failure_counter_decays_after_the_window(client, make_user, app, clock):
    await make_user()
    for _ in range(4):
        assert (await post(client, "WrongGuess01x")).status_code == 401
    clock.advance(minutes=16)                           # LOGIN_FAILURE_WINDOW_MINUTES = 15
    assert (await post(client, "WrongGuess01x")).status_code == 401
    count, locked_until = (await sql(app, "SELECT failed_login_count, locked_until FROM users"))[0]
    assert (count, locked_until) == (1, None)           # restarted at 1, not locked at 5
    assert (await post(client, GOOD_PASSWORD)).status_code == 200


async def test_failures_inside_the_window_still_accumulate(client, make_user, clock):
    await make_user()
    for _ in range(4):
        await post(client, "WrongGuess01x")
        clock.advance(minutes=3)                        # 12 minutes in total: inside the window
    assert (await post(client, "WrongGuess01x")).status_code == 401      # 5th failure -> locks
    assert (await post(client, GOOD_PASSWORD)).status_code == 429
