import logging

from tests.jwt_helpers import claims, sign

OTHER_USER = "2c8d7e4f-9b1a-4d66-8b8f-2a3e4d5c6b7a"


async def login(pipe):
    return await pipe.client.post("/api/auth/login", content=b"{}")


async def test_sixth_login_attempt_is_429_with_retry_after_and_policy(pipe):
    for _ in range(5):
        assert (await login(pipe)).status_code == 200
    r = await login(pipe)
    err = r.json()["error"]
    assert r.status_code == 429 and err["code"] == "RATE_LIMITED"
    assert err["details"] == [{"policy": "auth_login"}]
    assert r.headers["retry-after"] == "6" and "6 seconds" in err["message"]
    assert len(pipe.ups["auth"].requests) == 5                              # the sixth never reached auth-svc


async def test_login_bucket_refills_with_time(pipe):
    for _ in range(6):
        await login(pipe)
    pipe.clock.advance(6)
    assert (await login(pipe)).status_code == 200
    assert (await login(pipe)).status_code == 429


async def test_signup_shares_the_login_bucket_and_other_ips_are_independent(pipe):
    for _ in range(3):
        await login(pipe)
    for _ in range(2):
        await pipe.client.post("/api/auth/signup", content=b"{}")
    assert (await login(pipe)).status_code == 429


async def test_refresh_has_its_own_bigger_bucket(pipe):
    for _ in range(6):
        await login(pipe)
    for _ in range(20):
        assert (await pipe.client.post("/api/auth/refresh", content=b"{}")).status_code == 200
    r = await pipe.client.post("/api/auth/refresh", content=b"{}")
    assert r.status_code == 429 and r.json()["error"]["details"] == [{"policy": "auth_refresh"}]


async def test_user_default_limit_is_per_user(pipe):
    for _ in range(100):
        assert (await pipe.client.get("/api/patients", headers=pipe.auth)).status_code == 200
    r = await pipe.client.get("/api/patients", headers=pipe.auth)
    assert r.status_code == 429 and r.json()["error"]["details"] == [{"policy": "user_default"}]
    other = {"Authorization": "Bearer " + sign(pipe.key, claims(pipe.clock.wall(), sub=OTHER_USER))}
    assert (await pipe.client.get("/api/patients", headers=other)).status_code == 200


async def test_ai_polling_never_eats_the_general_budget(pipe):
    for _ in range(60):
        assert (await pipe.client.get("/api/ai/summaries/7", headers=pipe.auth)).status_code == 200
    r = await pipe.client.get("/api/ai/summaries/7", headers=pipe.auth)
    assert r.status_code == 429 and r.json()["error"]["details"] == [{"policy": "ai_poll"}]
    assert (await pipe.client.get("/api/patients", headers=pipe.auth)).status_code == 200      # untouched


async def test_ai_generate_is_tight(pipe):
    path = "/api/ai/patients/0b7c1e2a-4d5f-4a6b-8c7d-0e1f2a3b5a69/summary"
    for _ in range(3):
        assert (await pipe.client.post(path, content=b"{}", headers=pipe.auth)).status_code == 200
    r = await pipe.client.post(path, content=b"{}", headers=pipe.auth)
    assert r.status_code == 429 and r.json()["error"]["details"] == [{"policy": "ai_generate"}]


async def test_ip_global_limit_applies_to_everything(make_pipe):
    p = await make_pipe(rl_ip_global_burst=3, rl_ip_global_per_min=60)
    for _ in range(3):
        assert (await p.client.get("/api/patients", headers=p.auth)).status_code == 200
    r = await p.client.get("/api/patients", headers=p.auth)
    assert r.status_code == 429 and r.json()["error"]["details"] == [{"policy": "ip_global"}]


async def test_forwarded_for_from_the_client_cannot_dodge_the_ip_limit(pipe):
    for i in range(5):
        await pipe.client.post("/api/auth/login", content=b"{}", headers={"X-Forwarded-For": f"10.0.0.{i}"})
    r = await pipe.client.post("/api/auth/login", content=b"{}", headers={"X-Forwarded-For": "10.9.9.9"})
    assert r.status_code == 429                                              # R13: the socket peer decides


async def test_trusted_proxy_hops_use_the_forwarded_chain(make_pipe):
    p = await make_pipe(trust_proxy_hops=1)
    hdr = lambda ip: {"X-Forwarded-For": f"6.6.6.6, {ip}"}  # noqa: E731  (the client prepends junk)
    for _ in range(5):
        await p.client.post("/api/auth/login", content=b"{}", headers=hdr("198.51.100.1"))
    assert (await p.client.post("/api/auth/login", content=b"{}", headers=hdr("198.51.100.1"))).status_code == 429
    assert (await p.client.post("/api/auth/login", content=b"{}", headers=hdr("198.51.100.2"))).status_code == 200


async def test_rate_limit_can_be_turned_off(make_pipe):
    p = await make_pipe(rate_limit_enabled=False)
    for _ in range(20):
        assert (await p.client.post("/api/auth/login", content=b"{}")).status_code == 200


async def test_429_is_logged_as_rate_limited(pipe, caplog):
    for _ in range(5):
        await login(pipe)
    with caplog.at_level(logging.INFO, logger="nephro.access"):
        await login(pipe)
    rec = [r for r in caplog.records if r.name == "nephro.access"][-1]
    assert rec.status == 429 and rec.rate_limited is True and rec.route == "/api/auth/login"


async def test_auth_svcs_own_429_passes_through_beside_the_gateways(pipe):
    """The inner layer (auth-svc ACCOUNT_LOCKED / RATE_LIMITED) is untouched by the outer one."""
    import httpx

    body = {"error": {"code": "ACCOUNT_LOCKED", "message": "locked", "details": [], "request_id": "svc"}}
    pipe.ups["auth"]._handler = lambda req: httpx.Response(429, json=body, headers={"Retry-After": "900"})
    r = await login(pipe)
    assert r.status_code == 429 and r.json() == body and r.headers["retry-after"] == "900"
