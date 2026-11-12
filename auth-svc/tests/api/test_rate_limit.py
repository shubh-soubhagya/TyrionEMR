"""Item 2: per-IP token bucket and bounded hash queue."""
import asyncio

import httpx
import pytest

from app.core.ratelimit import TokenBucketLimiter
from app.domain.clock import FakeClock
from tests.conftest import GOOD_PASSWORD, client_for

pytestmark = pytest.mark.api
BODY = {"email": "nobody@nephrocare.demo", "password": "WrongGuess01x"}


def client_from(app, ip: str) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False, client=(ip, 5555))
    return httpx.AsyncClient(transport=transport, base_url="https://auth.test")


async def test_sixth_login_in_a_burst_is_429_with_retry_after(make_app):
    app = await make_app(rate_limit_enabled=True)       # defaults: 10/min sustained, burst 5
    async with client_from(app, "10.0.0.1") as c:
        codes = [(await c.post("/auth/login", json=BODY)).status_code for _ in range(5)]
        assert codes == [401] * 5
        r = await c.post("/auth/login", json=BODY)
    assert r.status_code == 429 and r.json()["error"]["code"] == "RATE_LIMITED"
    assert int(r.headers["retry-after"]) >= 1


async def test_another_ip_is_unaffected(make_app):
    app = await make_app(rate_limit_enabled=True)
    async with client_from(app, "10.0.0.1") as a, client_from(app, "10.0.0.2") as b:
        for _ in range(6):
            await a.post("/auth/login", json=BODY)
        assert (await a.post("/auth/login", json=BODY)).status_code == 429
        assert (await b.post("/auth/login", json=BODY)).status_code == 401


async def test_tokens_refill_with_the_injected_clock(make_app, clock):
    app = await make_app(rate_limit_enabled=True)
    async with client_from(app, "10.0.0.1") as c:
        for _ in range(5):
            await c.post("/auth/login", json=BODY)
        blocked = await c.post("/auth/login", json=BODY)
        assert blocked.status_code == 429 and blocked.headers["retry-after"] == "6"   # 10/min = 1 per 6 s
        clock.advance(seconds=6)
        assert (await c.post("/auth/login", json=BODY)).status_code == 401
        assert (await c.post("/auth/login", json=BODY)).status_code == 429


async def test_signup_is_limited_too(make_app):
    app = await make_app(rate_limit_enabled=True)
    async with client_from(app, "10.0.0.1") as c:
        for _ in range(5):
            await c.post("/auth/signup", json={"full_name": "Dr X", "email": "x@y.test", "password": "short"})
        r = await c.post("/auth/signup", json={"full_name": "Dr X", "email": "x@y.test", "password": "short"})
    assert r.status_code == 429


async def test_limiter_can_be_disabled(make_app):
    app = await make_app(rate_limit_enabled=False)
    async with client_from(app, "10.0.0.1") as c:
        assert {(await c.post("/auth/login", json=BODY)).status_code for _ in range(12)} == {401}


def test_bucket_map_is_bounded_and_evicts_least_recently_used():
    lim = TokenBucketLimiter(per_min=10, burst=5, clock=FakeClock(), max_keys=3)
    for ip in ("a", "b", "c"):
        lim.check(ip)
    lim.check("a")                                       # a is now the most recent
    lim.check("d")                                       # evicts b, the least recently used
    assert len(lim) == 3
    assert set(lim._buckets) == {"c", "a", "d"}
    for i in range(1000):
        lim.check(f"ip{i}")
    assert len(lim) == 3                                 # never grows past the cap


# ------------------------------------------------------------------------- bounded hash queue
async def test_saturated_hash_pool_returns_503_quickly(make_app, make_user):
    app = await make_app(argon2_max_concurrency=1, argon2_queue_timeout_s=0.2)
    await app.state.hasher._sem.acquire()
    try:
        async with client_for(app) as c:
            loop = asyncio.get_running_loop()
            start = loop.time()
            login = await c.post("/auth/login", json=BODY)                # unknown email -> dummy verify
            signup = await c.post("/auth/signup", json={"full_name": "Dr. New", "email": "n@y.test",
                                                         "password": GOOD_PASSWORD})
            elapsed = loop.time() - start
            metrics = (await c.get("/metrics")).text
    finally:
        app.state.hasher._sem.release()
    for r in (login, signup):
        assert r.status_code == 503 and r.json()["error"]["code"] == "SERVICE_BUSY"
        assert r.headers["retry-after"] == "1"
    assert elapsed < 1.5                                 # waited ~0.2 s each, did not hang
    assert "auth_argon2_rejected_total" in metrics and "auth_argon2_rejected_total 0.0" not in metrics


async def test_pool_recovers_after_a_rejection(make_app):
    app = await make_app(argon2_max_concurrency=1, argon2_queue_timeout_s=0.2)
    await app.state.hasher._sem.acquire()
    async with client_for(app) as c:
        assert (await c.post("/auth/login", json=BODY)).status_code == 503
        app.state.hasher._sem.release()
        assert (await c.post("/auth/login", json=BODY)).status_code == 401
