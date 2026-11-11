import pytest

from app.services.password_hasher import PasswordHasherService
from tests.conftest import GOOD_PASSWORD, client_for, make_settings, set_cookie_headers, sql

pytestmark = pytest.mark.api
EMAIL = "dr.rao@nephrocare.demo"


async def login(client, email=EMAIL, password=GOOD_PASSWORD):
    return await client.post("/auth/login", json={"email": email, "password": password})


async def test_login_success(client, make_user):
    await make_user()
    r = await login(client)
    assert r.status_code == 200
    j = r.json()
    assert j["access_token"] and j["user"]["full_name"] == "Dr. Anita Rao"
    assert r.headers["cache-control"] == "no-store"
    assert len(set_cookie_headers(r)) == 1


async def test_email_is_case_insensitive(client, make_user):
    await make_user()
    assert (await login(client, email="DR.RAO@NephroCare.demo")).status_code == 200


async def test_unknown_email_and_wrong_password_look_identical(client, make_user):
    await make_user()
    a = await login(client, email="nobody@nephrocare.demo")
    b = await login(client, password="WrongPassword99")
    assert a.status_code == b.status_code == 401
    ea, eb = a.json()["error"], b.json()["error"]
    assert ea["code"] == eb["code"] == "INVALID_CREDENTIALS"
    assert ea["message"] == eb["message"] == "Invalid email or password."
    assert ea["details"] == eb["details"] == []
    assert set_cookie_headers(a) == set_cookie_headers(b) == []


async def test_unknown_email_runs_a_dummy_verify(client, app, monkeypatch):
    calls = []
    original = app.state.hasher.verify_dummy

    async def spy(pw):
        calls.append(1)
        await original(pw)

    monkeypatch.setattr(app.state.hasher, "verify_dummy", spy)
    await login(client, email="nobody@nephrocare.demo")
    assert calls == [1]


async def test_inactive_user_with_correct_password_is_403(client, make_user):
    await make_user(active=False)
    r = await login(client)
    assert r.status_code == 403 and r.json()["error"]["code"] == "ACCOUNT_DISABLED"


async def test_inactive_user_with_wrong_password_is_still_401(client, make_user):
    await make_user(active=False)
    assert (await login(client, password="WrongPassword99")).status_code == 401


async def test_malformed_body_is_422(client):
    r = await client.post("/auth/login", json={"email": "x"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_login_updates_last_login_at(client, make_user, app):
    await make_user()
    await login(client)
    assert (await sql(app, "SELECT last_login_at FROM users"))[0][0] == app.state.clock()


async def test_rehash_happens_when_cost_settings_change(make_app):
    old_hash = await PasswordHasherService(make_settings(argon2_time_cost=1)).hash(GOOD_PASSWORD)
    app = await make_app(argon2_time_cost=2)
    async with app.state.sessionmaker() as s, s.begin():
        from sqlalchemy import text
        await s.execute(text(
            "INSERT INTO users (id,email,password_hash,full_name) VALUES (gen_random_uuid(),:e,:h,'Dr. Rao')"),
            {"e": EMAIL, "h": old_hash})
    async with client_for(app) as c:
        r = await login(c)
    assert r.status_code == 200
    new_hash = (await sql(app, "SELECT password_hash FROM users"))[0][0]
    assert new_hash != old_hash and "t=2" in new_hash
