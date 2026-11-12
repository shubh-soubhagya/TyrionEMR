import pytest

from tests.conftest import client_for

pytestmark = pytest.mark.api


async def test_metrics_can_be_turned_off(make_app):
    app = await make_app(metrics_enabled=False)
    async with client_for(app) as c:
        r = await c.get("/metrics")
        assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"
        assert (await c.get("/health")).status_code == 200


async def test_metrics_are_on_by_default(client):
    assert (await client.get("/metrics")).status_code == 200
