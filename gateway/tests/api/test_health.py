import logging

from app.core.metrics import HTTP_DURATION


async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    assert r.headers["x-request-id"].startswith("req-")


async def test_request_id_is_propagated_when_valid_and_replaced_when_not(client):
    assert (await client.get("/health", headers={"X-Request-ID": "req-from-client"})).headers[
        "x-request-id"] == "req-from-client"
    bad = await client.get("/health", headers={"X-Request-ID": "bad id with spaces"})
    assert bad.headers["x-request-id"].startswith("req-") and " " not in bad.headers["x-request-id"]


async def test_health_is_logged_with_a_literal_route_label(client, caplog):
    with caplog.at_level(logging.INFO, logger="nephro.access"):
        await client.get("/health?secret=1")
    rec = next(r for r in caplog.records if r.name == "nephro.access")
    assert rec.route == "/health" and rec.status == 200
    assert "secret" not in str(rec.__dict__)


async def test_unmatched_route_label(client, caplog):
    with caplog.at_level(logging.INFO, logger="nephro.access"):
        await client.get("/anything/at/all")
    rec = next(r for r in caplog.records if r.name == "nephro.access")
    assert rec.route == "unmatched"


async def test_health_is_not_in_the_histogram(client):
    def count() -> float:
        return sum(s.value for m in HTTP_DURATION.collect() for s in m.samples
                   if s.name.endswith("_count") and s.labels["route"] == "/health")

    before = count()
    await client.get("/health")
    assert count() == before
