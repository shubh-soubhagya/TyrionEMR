import pytest

from tests.jwt_helpers import USER_ID, claims, new_key, sign

PUBLIC = [("POST", "/api/auth/login"), ("POST", "/api/auth/signup"), ("POST", "/api/auth/refresh"),
          ("POST", "/api/auth/logout")]


@pytest.mark.parametrize(("method", "path"), PUBLIC)
async def test_public_auth_routes_need_no_token(pipe, method, path):
    r = await pipe.client.request(method, path, content=b"{}")
    assert r.status_code == 200 and pipe.ups["auth"].last.url.path == path.removeprefix("/api")


@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", "/api/patients"), ("GET", "/api/auth/me"), ("POST", "/api/auth/password"),
     ("GET", "/api/auth/login"), ("POST", "/api/auth/login/"), ("GET", "/api/labs/x"), ("GET", "/api/ai/x")],
)
async def test_everything_else_needs_a_token(pipe, method, path):
    r = await pipe.client.request(method, path)
    assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHENTICATED"
    assert all(not rec.requests for rec in pipe.ups.values())             # nothing reached a service


async def test_valid_token_is_forwarded_unchanged_and_nothing_is_added(pipe):
    token = pipe.token()
    r = await pipe.client.get("/api/patients", headers={"Authorization": f"Bearer {token}", "X-User-Id": "evil"})
    assert r.status_code == 200
    sent = pipe.ups["patient"].last.headers
    assert sent["authorization"] == f"Bearer {token}"                      # byte for byte
    assert "x-user-id" not in sent and "x-role" not in sent and "x-forwarded-user" not in sent


async def test_expired_token_is_token_expired(pipe):
    token = pipe.token()
    pipe.clock.advance(900 + 31)
    r = await pipe.client.get("/api/patients", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "TOKEN_EXPIRED"


@pytest.mark.parametrize("header", ["Bearer", "Bearer ", "Basic abc", "Bearer not.a.jwt", "Token abc", ""])
async def test_bad_authorization_headers_are_unauthenticated(pipe, header):
    r = await pipe.client.get("/api/patients", headers={"Authorization": header})
    assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHENTICATED"


@pytest.mark.parametrize("over", [{"aud": "other"}, {"iss": "evil"}, {"sub": "not-a-uuid"}, {"exp": None}])
async def test_invalid_claims_are_unauthenticated(pipe, over):
    r = await pipe.client.get("/api/patients", headers={"Authorization": "Bearer " + pipe.token(**over)})
    assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_token_signed_by_an_unknown_key_is_refused(pipe):
    forged = sign(new_key(), claims(pipe.clock.wall()))
    r = await pipe.client.get("/api/patients", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401 and not pipe.ups["patient"].requests


async def test_the_gateway_authenticates_but_does_not_authorize(pipe):
    """ADR-G6: the role claim is not checked here; services decide who may do what."""
    r = await pipe.client.get("/api/patients", headers={"Authorization": "Bearer " + pipe.token(role="receptionist")})
    assert r.status_code == 200


async def test_user_id_reaches_the_access_log(pipe, caplog):
    import logging

    with caplog.at_level(logging.INFO, logger="nephro.access"):
        await pipe.client.get("/api/patients", headers=pipe.auth)
    rec = next(r for r in caplog.records if r.name == "nephro.access")
    assert rec.user_id == USER_ID and rec.route == "/api/patients"


async def test_gateway_401_is_an_envelope_with_the_request_id(pipe):
    r = await pipe.client.get("/api/patients")
    assert r.json()["error"]["request_id"] == r.headers["x-request-id"]


async def test_auth_failures_do_not_consume_a_user_bucket(pipe):
    for _ in range(150):
        await pipe.client.get("/api/patients")
    assert (await pipe.client.get("/api/patients", headers=pipe.auth)).status_code == 200


async def test_keys_missing_means_401_for_everyone(make_pipe):
    p = await make_pipe()
    p.app.state.jwks._last_success = None                                # as if no fetch ever succeeded
    p.app.state.jwks._keys = {}
    p.app.state.jwks._last_attempt = float("inf")                        # and the refetch is rate-limited
    r = await p.client.get("/api/patients", headers=p.auth)
    assert r.status_code == 401
