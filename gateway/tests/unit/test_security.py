"""Repeats auth-svc's token cases (tests/unit/test_token_service.py) plus the gateway-side extras,
so the two copies of verify_access_token cannot drift unnoticed."""
import json

import jwt
import pytest
from cryptography.hazmat.primitives import serialization

from app.core.errors import TokenExpired, Unauthenticated
from app.core.security import Claims, unverified_kid, verify_access_token
from app.domain.clock import FakeClock
from tests.jwt_helpers import USER_ID, b64, claims, kid_of, new_key, sign

ISS, AUD = "nephro-auth", "nephro-api"


@pytest.fixture(scope="module")
def key():
    return new_key()


@pytest.fixture
def keys(key):
    return {kid_of(key): key.public_key()}


@pytest.fixture
def clock():
    return FakeClock()


def verify(token, keys, clock, **kw):
    return verify_access_token(token, keys, issuer=ISS, audience=AUD, now=clock.wall(), **kw)


def test_roundtrip(key, keys, clock):
    c = verify(sign(key, claims(clock.wall())), keys, clock)
    assert isinstance(c, Claims) and c.sub == USER_ID and c.role == "clinician"


def test_rejects_wrong_audience(key, keys, clock):
    with pytest.raises(Unauthenticated):
        verify(sign(key, claims(clock.wall(), aud="other")), keys, clock)


def test_rejects_wrong_issuer(key, keys, clock):
    with pytest.raises(Unauthenticated):
        verify(sign(key, claims(clock.wall(), iss="evil")), keys, clock)


def test_rejects_expired_with_the_injected_clock(key, keys, clock):
    token = sign(key, claims(clock.wall()))
    clock.advance(900 + 29)
    assert verify(token, keys, clock)                      # inside the 30 s leeway
    clock.advance(2)
    with pytest.raises(TokenExpired):
        verify(token, keys, clock)


@pytest.mark.parametrize("missing", ["exp", "iat", "sub", "iss", "aud"])
def test_rejects_missing_required_claim(key, keys, clock, missing):
    with pytest.raises(Unauthenticated):
        verify(sign(key, claims(clock.wall(), **{missing: None})), keys, clock)


def test_rejects_hs256_signed_with_the_public_key(key, keys, clock):
    """Key-confusion attack: HS256 with the RSA public key as the HMAC secret."""
    pem = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    header = b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": kid_of(key)}).encode())
    body = b64(json.dumps(claims(clock.wall())).encode())
    import hashlib
    import hmac
    sig = b64(hmac.new(pem, f"{header}.{body}".encode(), hashlib.sha256).digest())
    with pytest.raises(Unauthenticated):
        verify(f"{header}.{body}.{sig}", keys, clock)


def test_rejects_alg_none(key, keys, clock):
    header = b64(json.dumps({"alg": "none", "typ": "JWT", "kid": kid_of(key)}).encode())
    body = b64(json.dumps(claims(clock.wall())).encode())
    with pytest.raises(Unauthenticated):
        verify(f"{header}.{body}.", keys, clock)


def test_rejects_unknown_kid(key, keys, clock):
    with pytest.raises(Unauthenticated):
        verify(sign(key, claims(clock.wall()), kid="not-a-known-kid"), keys, clock)


def test_rejects_a_token_signed_by_a_different_key(keys, clock):
    other = new_key()
    with pytest.raises(Unauthenticated):
        verify(sign(other, claims(clock.wall()), kid=next(iter(keys))), keys, clock)


@pytest.mark.parametrize("garbage", ["", "abc", "a.b.c", "a.b", "....", "Bearer x"])
def test_rejects_garbage(keys, clock, garbage):
    with pytest.raises(Unauthenticated):
        verify(garbage, keys, clock)


@pytest.mark.parametrize("sub", ["u", "123", "not-a-uuid", ""])
def test_sub_must_be_a_uuid(key, keys, clock, sub):
    """auth-svc D23: the ids are UUIDs, so a token with anything else is refused."""
    with pytest.raises(Unauthenticated):
        verify(sign(key, claims(clock.wall(), sub=sub)), keys, clock)


def test_token_issued_in_the_future_is_refused(key, keys, clock):
    token = sign(key, claims(clock.wall() + 3600, nbf=None))
    with pytest.raises(Unauthenticated):
        verify(token, keys, clock)


def test_non_numeric_time_claims_are_refused(key, keys, clock):
    token = sign(key, claims(clock.wall(), exp="soon"))
    with pytest.raises(Unauthenticated):
        verify(token, keys, clock)


def test_role_is_read_but_not_enforced_here(key, keys, clock):
    assert verify(sign(key, claims(clock.wall(), role="anything")), keys, clock).role == "anything"


def test_unverified_kid(key):
    token = sign(key, claims(0))
    assert unverified_kid(token) == kid_of(key)


@pytest.mark.parametrize("bad", ["garbage", "e30.e30.e30"])
def test_unverified_kid_rejects_malformed(bad):
    with pytest.raises(Unauthenticated):
        unverified_kid(bad)


def test_unverified_kid_rejects_wrong_alg_and_overlong_kid(key):
    assert jwt.get_unverified_header(sign(key, claims(0)))["alg"] == "RS256"
    with pytest.raises(Unauthenticated):
        unverified_kid(sign(key, claims(0), kid="k" * 129))
    hs = jwt.encode({"a": 1}, "secret-that-is-long-enough-for-hmac-sha256", algorithm="HS256", headers={"kid": "x"})
    with pytest.raises(Unauthenticated):
        unverified_kid(hs)
