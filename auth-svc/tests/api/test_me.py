import pytest
from sqlalchemy import text

from tests.conftest import GOOD_PASSWORD

pytestmark = pytest.mark.api
EMAIL = "dr.rao@nephrocare.demo"


async def token(client, make_user):
    await make_user()
    r = await client.post("/auth/login", json={"email": EMAIL, "password": GOOD_PASSWORD})
    return r.json()["access_token"]


def bearer(t):
    return {"authorization": f"Bearer {t}"}


async def test_me_returns_the_user(client, make_user):
    r = await client.get("/auth/me", headers=bearer(await token(client, make_user)))
    assert r.status_code == 200
    assert r.json()["email"] == EMAIL and r.json()["full_name"] == "Dr. Anita Rao" and r.json()["role"] == "clinician"


async def test_me_without_token_is_401(client):
    r = await client.get("/auth/me")
    assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_me_with_garbage_or_wrong_scheme_is_401(client):
    assert (await client.get("/auth/me", headers=bearer("garbage"))).status_code == 401
    assert (await client.get("/auth/me", headers={"authorization": "Basic abc"})).status_code == 401


async def test_me_with_expired_token_is_token_expired(client, make_user, clock):
    t = await token(client, make_user)
    clock.advance(minutes=15, seconds=29)           # inside the 30 s leeway: still valid
    assert (await client.get("/auth/me", headers=bearer(t))).status_code == 200
    clock.advance(seconds=2)
    r = await client.get("/auth/me", headers=bearer(t))
    assert r.status_code == 401 and r.json()["error"]["code"] == "TOKEN_EXPIRED"


async def test_me_for_inactive_user_is_403(client, make_user, app):
    t = await token(client, make_user)
    async with app.state.sessionmaker() as s, s.begin():
        await s.execute(text("UPDATE users SET is_active = false"))
    r = await client.get("/auth/me", headers=bearer(t))
    assert r.status_code == 403 and r.json()["error"]["code"] == "ACCOUNT_DISABLED"


async def test_me_for_deleted_user_is_404(client, make_user, app):
    t = await token(client, make_user)
    async with app.state.sessionmaker() as s, s.begin():
        await s.execute(text("DELETE FROM users"))
    r = await client.get("/auth/me", headers=bearer(t))
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"
