"""AuthGate in isolation (the full pipeline test is tests/api/test_auth_gate.py in Phase 5)."""
import logging

import pytest
from starlette.requests import Request

from app.core.config import Settings
from app.core.errors import TokenExpired, Unauthenticated
from app.domain.clock import FakeClock
from app.services.auth_gate import AuthGate
from app.services.jwks_cache import JwksCache
from tests.jwt_helpers import USER_ID, claims, jwks_doc, kid_of, new_key, sign


@pytest.fixture(scope="module")
def key():
    return new_key()


def request_with(authorization: str | None) -> Request:
    headers = [(b"authorization", authorization.encode())] if authorization is not None else []
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers, "state": {}})


@pytest.fixture
async def gate(key):
    clock = FakeClock()
    settings = Settings(_env_file=None)

    async def fetch():
        return jwks_doc(key)

    jwks = JwksCache(fetch, settings, clock)
    await jwks.refresh("startup")
    return AuthGate(jwks, settings, clock), clock


async def test_valid_token_sets_user_id(gate, key):
    g, clock = gate
    req = request_with("Bearer " + sign(key, claims(clock.wall())))
    c = await g.authenticate(req)
    assert c.sub == USER_ID and req.state.user_id == USER_ID


@pytest.mark.parametrize("header", [None, "", "Basic abc", "Bearer", "Bearer ", "bearer"])
async def test_missing_or_malformed_header(gate, header):
    g, _ = gate
    with pytest.raises(Unauthenticated):
        await g.authenticate(request_with(header))


async def test_expired_is_its_own_code(gate, key):
    g, clock = gate
    token = sign(key, claims(clock.wall()))
    clock.advance(2000)
    with pytest.raises(TokenExpired):
        await g.authenticate(request_with("Bearer " + token))


async def test_unknown_kid_and_wrong_key(gate, key):
    g, clock = gate
    with pytest.raises(Unauthenticated):
        await g.authenticate(request_with("Bearer " + sign(key, claims(clock.wall()), kid="zzz")))
    other = new_key()
    with pytest.raises(Unauthenticated):
        await g.authenticate(request_with("Bearer " + sign(other, claims(clock.wall()), kid=kid_of(key))))


async def test_rejections_log_the_reason_only(gate, key, caplog):
    g, clock = gate
    token = sign(key, claims(clock.wall(), aud="other"))
    with caplog.at_level(logging.INFO, logger="gateway.auth"), pytest.raises(Unauthenticated):
        await g.authenticate(request_with("Bearer " + token))
    rec = next(r for r in caplog.records if r.name == "gateway.auth")
    assert rec.reason == "invalid"
    assert token not in caplog.text and token not in str(rec.__dict__)
