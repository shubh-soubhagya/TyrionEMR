import base64
import json
import re
import uuid
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.errors import TokenExpired, Unauthenticated
from app.services.keystore import KeyStore, SigningKey, thumbprint_kid
from app.services.token_service import TokenService
from tests.conftest import make_settings

USER = SimpleNamespace(id=uuid.UUID("1b7c6d3e-8a0f-4c55-9a7e-1f2d3c4b5a69"), role="clinician")


@pytest.fixture
def keystore(rsa_key):
    pub = rsa_key.public_key()
    kid = thumbprint_kid(pub)
    return KeyStore(SigningKey(kid, rsa_key), {kid: pub})


@pytest.fixture
def svc(keystore, clock):
    return TokenService(keystore, make_settings(), clock)


def test_claims_and_header(svc, keystore):
    token, ttl = svc.issue_access_token(USER)
    assert ttl == 900
    header = jwt.get_unverified_header(token)
    assert header["kid"] == keystore.active.kid and header["alg"] == "RS256"
    claims = jwt.decode(token, options={"verify_signature": False})
    assert set(claims) == {"iss", "aud", "sub", "role", "iat", "nbf", "exp", "jti"}   # no PII
    assert claims["exp"] - claims["iat"] == 900
    assert claims["iss"] == "nephro-auth" and claims["aud"] == "nephro-api"
    assert claims["sub"] == str(USER.id) and claims["role"] == "clinician"


def test_roundtrip(svc):
    token, _ = svc.issue_access_token(USER)
    assert svc.verify_access_token(token).sub == str(USER.id)


def _encode(keystore, claims, **kw):
    return jwt.encode(claims, keystore.active.private_key, algorithm="RS256",
                      headers={"kid": keystore.active.kid}, **kw)


def _claims(clock, **over):
    now = int(clock().timestamp())
    base = {"iss": "nephro-auth", "aud": "nephro-api", "sub": "u", "role": "clinician",
            "iat": now, "exp": now + 900}
    base.update(over)
    return base


def test_rejects_wrong_audience(svc, keystore, clock):
    with pytest.raises(Unauthenticated):
        svc.verify_access_token(_encode(keystore, _claims(clock, aud="other")))


def test_rejects_wrong_issuer(svc, keystore, clock):
    with pytest.raises(Unauthenticated):
        svc.verify_access_token(_encode(keystore, _claims(clock, iss="evil")))


def test_rejects_expired(svc, keystore):
    # real wall clock is used by PyJWT for exp; an old exp is far beyond the 30 s leeway
    with pytest.raises(TokenExpired):
        svc.verify_access_token(_encode(keystore, {"iss": "nephro-auth", "aud": "nephro-api",
                                                   "sub": "u", "iat": 1000, "exp": 1900}))


def test_rejects_missing_required_claim(svc, keystore, clock):
    c = _claims(clock)
    del c["sub"]
    with pytest.raises(Unauthenticated):
        svc.verify_access_token(_encode(keystore, c))


def test_rejects_hs256_signed_with_public_key(svc, keystore, clock):
    pem = keystore.active.private_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    # PyJWT refuses to HS-sign with a PEM key; build the forged token by hand (classic confusion attack)
    import hashlib
    import hmac

    def b64(b): return base64.urlsafe_b64encode(b).rstrip(b"=").decode()
    head = b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": keystore.active.kid}).encode())
    body = b64(json.dumps(_claims(clock)).encode())
    sig = b64(hmac.new(pem, f"{head}.{body}".encode(), hashlib.sha256).digest())
    with pytest.raises(Unauthenticated):
        svc.verify_access_token(f"{head}.{body}.{sig}")


def test_rejects_alg_none(svc, keystore, clock):
    def b64(b): return base64.urlsafe_b64encode(b).rstrip(b"=").decode()
    head = b64(json.dumps({"alg": "none", "typ": "JWT", "kid": keystore.active.kid}).encode())
    body = b64(json.dumps(_claims(clock)).encode())
    with pytest.raises(Unauthenticated):
        svc.verify_access_token(f"{head}.{body}.")


def test_rejects_unknown_kid(svc, clock):
    stranger = rsa.generate_private_key(65537, 2048)
    token = jwt.encode(_claims(clock), stranger, algorithm="RS256", headers={"kid": "nope"})
    with pytest.raises(Unauthenticated):
        svc.verify_access_token(token)


def test_rejects_garbage(svc):
    with pytest.raises(Unauthenticated):
        svc.verify_access_token("not-a-jwt")


def test_refresh_secret_shape():
    raw, h = TokenService.new_refresh_secret()
    raw2, _ = TokenService.new_refresh_secret()
    assert len(raw) == 43 and re.fullmatch(r"[A-Za-z0-9_-]+", raw)
    assert len(h) == 64 and re.fullmatch(r"[0-9a-f]+", h)
    assert raw != raw2
    assert TokenService.hash_refresh(raw) == h
