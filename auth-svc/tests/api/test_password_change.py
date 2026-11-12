"""Item 12: POST /auth/password."""
import pytest

from tests.conftest import GOOD_PASSWORD, rt_cookie, set_cookie_headers, sql, with_cookie

pytestmark = pytest.mark.api
EMAIL = "dr.rao@nephrocare.demo"
NEW = "Glomerular2027!x"
ORIGIN = {"origin": "http://localhost:4200"}


async def sign_in(client, password=GOOD_PASSWORD):
    r = await client.post("/auth/login", json={"email": EMAIL, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"], rt_cookie(r)


async def change(client, token, current=GOOD_PASSWORD, new=NEW, cookie=None, **headers):
    h = {"authorization": f"Bearer {token}", **ORIGIN, **headers}
    if cookie:
        h.update(with_cookie(cookie))
    return await client.post("/auth/password", json={"current_password": current, "new_password": new}, headers=h)


def code(r):
    return r.json()["error"]["code"]


async def test_success_keeps_this_session_and_signs_out_the_others(client, make_user, app):
    await make_user()
    token_a, rt_a = await sign_in(client)           # the session that changes the password
    _, rt_b = await sign_in(client)                 # another device

    r = await change(client, token_a, cookie=rt_a)
    assert r.status_code == 204 and r.content == b""
    assert r.headers["cache-control"] == "no-store"
    rt_a2 = rt_cookie(r)
    assert rt_a2 and rt_a2 != rt_a                  # this session's refresh token was rotated

    assert (await client.post("/auth/refresh", headers=with_cookie(rt_b))).status_code == 401   # other device out
    assert (await client.post("/auth/refresh", headers=with_cookie(rt_a2))).status_code == 200   # this one lives

    reasons = await sql(app, "SELECT revoked_reason, count(*) FROM refresh_tokens GROUP BY 1 ORDER BY 1 NULLS FIRST")
    assert ("password_changed", 1) in [(a, b) for a, b in reasons]

    assert (await client.post("/auth/login", json={"email": EMAIL, "password": GOOD_PASSWORD})).status_code == 401
    assert (await client.post("/auth/login", json={"email": EMAIL, "password": NEW})).status_code == 200


async def test_without_a_cookie_every_session_is_revoked_and_none_issued(client, make_user, app):
    await make_user()
    token, rt = await sign_in(client)
    r = await change(client, token)                 # no refresh cookie sent
    assert r.status_code == 204 and set_cookie_headers(r) == []
    assert (await client.post("/auth/refresh", headers=with_cookie(rt))).status_code == 401
    assert (await sql(app, "SELECT count(*) FROM refresh_tokens WHERE revoked_at IS NULL"))[0][0] == 0


async def test_wrong_current_password_is_rejected_and_changes_nothing(client, make_user, app):
    await make_user()
    token, rt = await sign_in(client)
    before = (await sql(app, "SELECT password_hash FROM users"))[0][0]
    r = await change(client, token, current="WrongPassword99", cookie=rt)
    assert r.status_code == 401 and code(r) == "INVALID_CREDENTIALS"
    assert r.json()["error"]["message"] == "Current password is incorrect."
    assert (await sql(app, "SELECT password_hash FROM users"))[0][0] == before
    assert (await client.post("/auth/refresh", headers=with_cookie(rt))).status_code == 200   # session intact


async def test_wrong_current_password_counts_toward_lockout(client, make_user):
    await make_user()
    token, _ = await sign_in(client)
    codes = [(await change(client, token, current="WrongPassword99")).status_code for _ in range(5)]
    assert codes == [401] * 5                        # the 5th failure locks, still 401
    r = await change(client, token, current=GOOD_PASSWORD)
    assert r.status_code == 429 and code(r) == "ACCOUNT_LOCKED"
    assert (await client.post("/auth/login", json={"email": EMAIL, "password": GOOD_PASSWORD})).status_code == 429


async def test_policy_failures_are_422_with_field_codes_and_nothing_changes(client, make_user, app):
    await make_user()
    token, rt = await sign_in(client)
    r = await change(client, token, new="short1", cookie=rt)
    assert r.status_code == 422 and code(r) == "VALIDATION_ERROR"
    assert {"TOO_SHORT"} <= {d["code"] for d in r.json()["error"]["details"]}
    assert all(d["field"] == "new_password" for d in r.json()["error"]["details"])
    assert "short1" not in r.text.replace("TOO_SHORT", "")

    same = await change(client, token, new=GOOD_PASSWORD, cookie=rt)
    assert same.status_code == 422 and "SAME_AS_CURRENT" in {d["code"] for d in same.json()["error"]["details"]}

    common = await change(client, token, new="Iloveyou123", cookie=rt)
    assert "TOO_COMMON" in {d["code"] for d in common.json()["error"]["details"]}
    assert (await sql(app, "SELECT count(*) FROM refresh_tokens WHERE revoked_at IS NULL"))[0][0] == 1


async def test_requires_a_bearer_token_and_a_trusted_origin(client, make_user):
    await make_user()
    token, rt = await sign_in(client)
    body = {"current_password": GOOD_PASSWORD, "new_password": NEW}
    assert (await client.post("/auth/password", json=body)).status_code == 401
    bad = await change(client, token, cookie=rt, origin="https://evil.example")
    assert bad.status_code == 403 and code(bad) == "ORIGIN_NOT_ALLOWED"


async def test_a_stolen_refresh_cookie_of_another_user_is_not_kept(client, make_user, app):
    """The cookie must belong to the caller: someone else's family is revoked like any other session."""
    await make_user()
    await make_user(email="dr.malhotra@nephrocare.demo", name="Dr. Karan Malhotra")
    token_a, _ = await sign_in(client)
    other = await client.post("/auth/login", json={"email": "dr.malhotra@nephrocare.demo", "password": GOOD_PASSWORD})
    rt_other = rt_cookie(other)
    r = await change(client, token_a, cookie=rt_other)
    assert r.status_code == 204 and set_cookie_headers(r) == []            # not rotated, not kept
    assert (await client.post("/auth/refresh", headers=with_cookie(rt_other))).status_code == 200   # untouched
