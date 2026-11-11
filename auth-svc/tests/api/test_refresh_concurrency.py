import asyncio

import pytest

from tests.conftest import GOOD_PASSWORD, rt_cookie, sql, with_cookie

pytestmark = pytest.mark.api


async def test_two_parallel_refreshes_give_exactly_one_200_and_one_409(client, make_user, app):
    await make_user()
    login = await client.post("/auth/login", json={"email": "dr.rao@nephrocare.demo", "password": GOOD_PASSWORD})
    rt = rt_cookie(login)

    r1, r2 = await asyncio.gather(
        client.post("/auth/refresh", headers=with_cookie(rt)),
        client.post("/auth/refresh", headers=with_cookie(rt)),
    )
    assert sorted([r1.status_code, r2.status_code]) == [200, 409]
    loser = r1 if r1.status_code == 409 else r2
    assert loser.json()["error"]["code"] == "REFRESH_RACE"
    # the family survives the race: one active token, nothing revoked as reuse
    assert (await sql(app, "SELECT count(*) FROM refresh_tokens WHERE revoked_at IS NULL"))[0][0] == 1
    assert (await sql(app, "SELECT count(*) FROM refresh_tokens WHERE revoked_reason='reuse_detected'"))[0][0] == 0


async def test_many_parallel_refreshes_still_issue_exactly_one_token(client, make_user, app):
    await make_user()
    login = await client.post("/auth/login", json={"email": "dr.rao@nephrocare.demo", "password": GOOD_PASSWORD})
    rt = rt_cookie(login)
    results = await asyncio.gather(*[client.post("/auth/refresh", headers=with_cookie(rt)) for _ in range(6)])
    statuses = sorted(r.status_code for r in results)
    assert statuses == [200] + [409] * 5
