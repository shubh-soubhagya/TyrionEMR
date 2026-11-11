import pytest

from tests.conftest import GOOD_PASSWORD, rt_cookie, set_cookie_headers, sql, with_cookie

pytestmark = pytest.mark.api


async def test_logout_without_cookie_is_204_and_clears(client):
    r = await client.post("/auth/logout")
    assert r.status_code == 204 and r.content == b""
    (c,) = set_cookie_headers(r)
    assert "Max-Age=0" in c and "Path=/api/auth" in c and "HttpOnly" in c
    assert r.headers["cache-control"] == "no-store"


async def test_logout_with_unknown_cookie_is_still_204(client):
    assert (await client.post("/auth/logout", headers=with_cookie("z" * 43))).status_code == 204


async def test_logout_revokes_family_and_blocks_refresh(client, make_user, app):
    await make_user()
    login = await client.post("/auth/login", json={"email": "dr.rao@nephrocare.demo", "password": GOOD_PASSWORD})
    rt = rt_cookie(login)
    rt2 = rt_cookie(await client.post("/auth/refresh", headers=with_cookie(rt)))
    r = await client.post("/auth/logout", headers=with_cookie(rt2))
    assert r.status_code == 204
    reasons = await sql(app, "SELECT revoked_reason FROM refresh_tokens WHERE revoked_reason='logout'")
    assert len(reasons) == 1                                   # only the active token needed revoking
    assert (await client.post("/auth/refresh", headers=with_cookie(rt2))).status_code == 401


async def test_logout_is_idempotent(client, make_user):
    await make_user()
    login = await client.post("/auth/login", json={"email": "dr.rao@nephrocare.demo", "password": GOOD_PASSWORD})
    rt = rt_cookie(login)
    assert (await client.post("/auth/logout", headers=with_cookie(rt))).status_code == 204
    assert (await client.post("/auth/logout", headers=with_cookie(rt))).status_code == 204


async def test_logout_rejects_untrusted_origin(client):
    r = await client.post("/auth/logout", headers={"origin": "https://evil.example"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "ORIGIN_NOT_ALLOWED"
