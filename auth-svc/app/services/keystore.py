"""Signing key, published public keys and JWKS. ``kid`` is the RFC 7638 JWK thumbprint (ADR-A7)."""
from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey


def _b64u_uint(n: int) -> str:
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _jwk(pub: RSAPublicKey) -> dict[str, str]:
    nums = pub.public_numbers()
    return {"kty": "RSA", "n": _b64u_uint(nums.n), "e": _b64u_uint(nums.e)}


def thumbprint_kid(pub: RSAPublicKey) -> str:
    jwk = _jwk(pub)
    # RFC 7638: required members only, lexicographic order, no whitespace
    canonical = json.dumps({"e": jwk["e"], "kty": "RSA", "n": jwk["n"]}, separators=(",", ":"))
    return base64.urlsafe_b64encode(hashlib.sha256(canonical.encode()).digest()).rstrip(b"=").decode()


@dataclass(frozen=True)
class SigningKey:
    kid: str
    private_key: RSAPrivateKey


class KeyStore:
    def __init__(self, active: SigningKey, published: dict[str, RSAPublicKey]) -> None:
        self.active = active
        self.published = published  # kid -> public key, includes the active key

    @classmethod
    def from_files(cls, private_path: str, extra_public_paths: list[str]) -> KeyStore:
        with open(private_path, "rb") as f:
            priv = serialization.load_pem_private_key(f.read(), password=None)
        if not isinstance(priv, RSAPrivateKey):
            raise RuntimeError("JWT signing key must be an RSA key")
        if priv.key_size < 2048:
            raise RuntimeError("JWT signing key must be at least 2048 bits")
        pub = priv.public_key()
        published: dict[str, RSAPublicKey] = {thumbprint_kid(pub): pub}
        for p in extra_public_paths:
            with open(p, "rb") as f:
                k = serialization.load_pem_public_key(f.read())
            if not isinstance(k, RSAPublicKey):
                raise RuntimeError(f"{p} is not an RSA public key")
            published[thumbprint_kid(k)] = k
        return cls(SigningKey(thumbprint_kid(pub), priv), published)

    def jwks(self) -> dict[str, Any]:
        return {"keys": [{**_jwk(k), "use": "sig", "alg": "RS256", "kid": kid}
                         for kid, k in self.published.items()]}
