import pytest

from tests.conftest import GOOD_PASSWORD, client_for, sql

pytestmark = pytest.mark.api
EMAIL = "dr.rao@nephrocare.demo"


async def attempt(client, password="WrongPassword99"):
    return await client.post("/auth/login", json={"email": EMAIL, "password": password})


async def fail_n(client, n):
    return [(await attempt(client)).status_code for _ in range(n)]


async def test_five_failures_return_401_then_sixth_is_429_with_retry_after(client, make_user):
    await make_user()
    assert await fail_n(client, 5) == [401] * 5        # the 5th failure locks but still answers 401
    r = await attempt(client)
    assert r.status_code == 429
    err = r.json()["error"]
    assert err["code"] == "ACCOUNT_LOCKED" and "15 minutes" in err["message"]
    assert r.headers["retry-after"] == str(15 * 60)


async def test_correct_password_is_rejected_while_locked_without_verifying(client, make_user, app, monkeypatch):
    await make_user()
    await fail_n(client, 5)
    verified = []
    original = app.state.hasher.verify

    async def spy(*a):
        verified.append(1)
        return await original(*a)

    monkeypatch.setattr(app.state.hasher, "verify", spy)
    r = await attempt(client, GOOD_PASSWORD)
    assert r.status_code == 429 and verified == []      # no hashing during a lock: no signal, no CPU


async def test_lock_expires_with_fake_clock(client, make_user, clock):
    await make_user()
    await fail_n(client, 5)
    clock.advance(minutes=14, seconds=59)
    assert (await attempt(client, GOOD_PASSWORD)).status_code == 429
    clock.advance(seconds=2)
    assert (await attempt(client, GOOD_PASSWORD)).status_code == 200


async def test_success_resets_the_counter(client, make_user, app):
    await make_user()
    await fail_n(client, 4)
    assert (await attempt(client, GOOD_PASSWORD)).status_code == 200
    assert (await sql(app, "SELECT failed_login_count, locked_until FROM users"))[0] == (0, None)
    assert await fail_n(client, 4) == [401] * 4          # would be locked if the counter had not reset
    assert (await attempt(client, GOOD_PASSWORD)).status_code == 200


async def test_lockout_reveal_false_returns_401_while_locked(make_app):
    app = await make_app(lockout_reveal=False)
    async with app.state.sessionmaker() as s, s.begin():
        from app.models import User
        import uuid
        s.add(User(id=uuid.uuid4(), email=EMAIL, full_name="Dr. Rao", role="clinician",
                   password_hash=await app.state.hasher.hash(GOOD_PASSWORD),
                   created_at=app.state.clock(), updated_at=app.state.clock()))
    async with client_for(app) as c:
        assert await fail_n(c, 5) == [401] * 5
        r = await attempt(c, GOOD_PASSWORD)
    assert r.status_code == 401 and r.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert "retry-after" not in r.headers


async def test_concurrent_failures_are_counted_atomically(client, make_user, app):
    import asyncio
    await make_user()
    await asyncio.gather(*[attempt(client) for _ in range(5)])
    # five parallel failures must land exactly on the threshold: locked, counter reset
    locked_until = (await sql(app, "SELECT locked_until FROM users"))[0][0]
    assert locked_until is not None
