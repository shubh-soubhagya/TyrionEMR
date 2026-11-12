"""Test helpers: sign access tokens with a test key and build JWKS documents. No network."""
from __future__ import annotations

import base64
import uuid
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from app.services.jwks_cache import _b64u_uint, thumbprint_kid

USER_ID = "1b7c6d3e-8a0f-4c55-9a7e-1f2d3c4b5a69"


def new_key(bits: int = 2048) -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=bits)


def kid_of(key: rsa.RSAPrivateKey) -> str:
    return thumbprint_kid(key.public_key())


def jwk_of(key: rsa.RSAPrivateKey, **overrides: Any) -> dict[str, Any]:
    nums = key.public_key().public_numbers()
    jwk = {"kty": "RSA", "use": "sig", "alg": "RS256", "kid": kid_of(key),
           "n": _b64u_uint(nums.n), "e": _b64u_uint(nums.e)}
    jwk.update(overrides)
    return jwk


def jwks_doc(*keys: rsa.RSAPrivateKey) -> dict[str, Any]:
    return {"keys": [jwk_of(k) for k in keys]}


def claims(now: float, **over: Any) -> dict[str, Any]:
    iat = int(now)
    base: dict[str, Any] = {"iss": "nephro-auth", "aud": "nephro-api", "sub": USER_ID, "role": "clinician",
                            "iat": iat, "nbf": iat, "exp": iat + 900, "jti": uuid.uuid4().hex}
    base.update(over)
    return {k: v for k, v in base.items() if v is not None}


def sign(key: rsa.RSAPrivateKey, payload: dict[str, Any], *, kid: str | None = None, alg: str = "RS256") -> str:
    return jwt.encode(payload, key, algorithm=alg, headers={"kid": kid if kid is not None else kid_of(key)})


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()
