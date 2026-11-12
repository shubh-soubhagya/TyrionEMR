"""Item 12: operator CLI commands (set_password, unlock_user, deactivate_user, revoke_sessions)."""
import pytest

from app.cli import deactivate_user, revoke_sessions, set_password, unlock_user
from app.core.config import get_settings
from tests.conftest import GOOD_PASSWORD, TEST_DB_URL, rt_cookie, sql, with_cookie

pytestmark = pytest.mark.api
EMAIL = "dr.rao@nephrocare.demo"
NEW = "Glomerular2027!x"


@pytest.fixture(autouse=True)
def cli_env(monkeypatch, migrated_db):
    """Point the CLI at the test database with cheap hashing."""
    monkeypatch.setenv("AUTH_DATABASE_URL", TEST_DB_URL)
    monkeypatch.setenv("ARGON2_TIME_COST", "1")
    monkeypatch.setenv("ARGON2_MEMORY_KIB", "1024")
    monkeypatch.setenv("ARGON2_PARALLELISM", "1")
    monkeypatch.setenv("ENVIRONMENT", "test")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def keyboard(*answers):
    it = iter(answers)
    return lambda _prompt: next(it)


async def sign_in(client, password=GOOD_PASSWORD):
    r = await client.post("/auth/login", json={"email": EMAIL, "password": password})
    return r, rt_cookie(r)


@pytest.mark.parametrize("module", [set_password, unlock_user, deactivate_user, revoke_sessions])
async def test_every_command_refuses_to_run_without_its_arguments(module):
    with pytest.raises(SystemExit) as exc:
        await module.main([])
    assert exc.value.code == 2


@pytest.mark.parametrize("module", [unlock_user, deactivate_user, revoke_sessions])
async def test_unknown_user_changes_nothing_and_exits_1(module, app, capsys):
    assert await module.main(["--email", "ghost@nephrocare.demo"]) == 1
    assert "Nothing changed" in capsys.readouterr().err
    assert (await sql(app, "SELECT count(*) FROM auth_events"))[0][0] == 0


async def test_unlock_user(client, make_user, app, capsys, clock):
    clock.sync_to_real_time()           # the CLI uses the real clock; the lock must be in its future
    await make_user()
    for _ in range(5):
        await client.post("/auth/login", json={"email": EMAIL, "password": "WrongPassword99"})
    assert (await sign_in(client))[0].status_code == 429

    assert await unlock_user.main(["--email", EMAIL]) == 0
    assert "cleared" in capsys.readouterr().out
    assert (await sql(app, "SELECT failed_login_count, locked_until, last_failed_at FROM users"))[0] == (0, None, None)
    assert (await sign_in(client))[0].status_code == 200
    assert [r[0] for r in await sql(app, "SELECT event FROM auth_events WHERE event='unlock'")] == ["unlock"]


async def test_unlock_on_a_clean_account_says_so(make_user, capsys):
    await make_user()
    assert await unlock_user.main(["--email", EMAIL]) == 0
    assert "nothing to clear" in capsys.readouterr().out


async def test_deactivate_user_signs_everyone_out_and_blocks_login(client, make_user, app, capsys):
    await make_user()
    _, rt_a = await sign_in(client)
    _, rt_b = await sign_in(client)

    assert await deactivate_user.main(["--email", EMAIL]) == 0
    assert "2 session(s) signed out" in capsys.readouterr().out
    assert (await sql(app, "SELECT is_active FROM users"))[0][0] is False
    for rt in (rt_a, rt_b):
        assert (await client.post("/auth/refresh", headers=with_cookie(rt))).status_code == 401
    assert (await sign_in(client))[0].status_code == 403
    assert {r[0] for r in await sql(app, "SELECT revoked_reason FROM refresh_tokens")} == {"user_inactive"}
    assert len(await sql(app, "SELECT 1 FROM auth_events WHERE event='deactivation'")) == 1

    assert await deactivate_user.main(["--email", EMAIL]) == 0                 # idempotent
    assert "already inactive" in capsys.readouterr().out


async def test_revoke_sessions_signs_out_but_keeps_the_account(client, make_user, app, capsys):
    await make_user()
    _, rt = await sign_in(client)
    assert await revoke_sessions.main(["--email", EMAIL]) == 0
    assert "1 session(s) signed out" in capsys.readouterr().out
    assert (await client.post("/auth/refresh", headers=with_cookie(rt))).status_code == 401
    assert (await sign_in(client))[0].status_code == 200                      # can sign in again
    assert len(await sql(app, "SELECT 1 FROM auth_events WHERE event='sessions_revoked'")) == 1


async def test_set_password_applies_policy_clears_lock_and_revokes_sessions(client, make_user, app, capsys):
    await make_user()
    _, rt = await sign_in(client)
    for _ in range(5):
        await client.post("/auth/login", json={"email": EMAIL, "password": "WrongPassword99"})
    before = (await sql(app, "SELECT password_hash FROM users"))[0][0]

    # policy failure: nothing changes
    assert await set_password.main(["--email", EMAIL], ask=keyboard("short1", "short1")) == 2
    assert "Nothing changed" in capsys.readouterr().err
    assert (await sql(app, "SELECT password_hash FROM users"))[0][0] == before
    # mismatch: nothing changes
    assert await set_password.main(["--email", EMAIL], ask=keyboard(NEW, NEW + "x")) == 2
    assert (await sql(app, "SELECT password_hash FROM users"))[0][0] == before

    assert await set_password.main(["--email", EMAIL], ask=keyboard(NEW, NEW)) == 0
    assert "Lock cleared" in capsys.readouterr().out
    assert (await sql(app, "SELECT locked_until FROM users"))[0][0] is None
    assert (await client.post("/auth/refresh", headers=with_cookie(rt))).status_code == 401
    assert (await sign_in(client, GOOD_PASSWORD))[0].status_code == 401
    assert (await sign_in(client, NEW))[0].status_code == 200
    assert len(await sql(app, "SELECT 1 FROM auth_events WHERE event='password_set'")) == 1
