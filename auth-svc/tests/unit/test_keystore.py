import base64

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.services.keystore import KeyStore, thumbprint_kid

# RFC 7638 section 3.1 example key and its published thumbprint
RFC_N = (
    "0vx7agoebGcQSuuPiLJXZptN9nndrQmbXEps2aiAFbWhM78LhWx4cbbfAAtVT86zwu1RK7aPFFxuhDR1L6tSoc_BJECPebWKRXjBZC"
    "iFV4n3oknjhMstn64tZ_2W-5JsGY4Hc5n9yBXArwl93lqt7_RN5w6Cf0h4QyQ5v-65YGjQR0_FDW2QvzqY368QQMicAtaSqzs8KJZg"
    "nYb9c7d0zgdAZHzu6qMQvRL5hajrn1n91CbOpbISD08qNLyrdkt-bFTWhAI4vMQFh6WeZu0fM4lFd2NcRwr3XPksINHaQ-G_xBniI"
    "qbw0Ls1jF44-csFCur-kEgU8awapJzKnqDKgw"
)
RFC_THUMBPRINT = "NzbLsXh8uDCcd-6MNwXF4W_7noWXFZAfHkxZsRGC9Xs"


def _b64u_int(s: str) -> int:
    return int.from_bytes(base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)), "big")


def _write_pem(path, key, private: bool):
    if private:
        data = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                 serialization.NoEncryption())
    else:
        data = key.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    path.write_bytes(data)


def test_kid_matches_rfc7638_vector():
    pub = rsa.RSAPublicNumbers(e=65537, n=_b64u_int(RFC_N)).public_key()
    assert thumbprint_kid(pub) == RFC_THUMBPRINT


def test_kid_is_stable(rsa_key):
    assert thumbprint_kid(rsa_key.public_key()) == thumbprint_kid(rsa_key.public_key())


def test_jwks_has_required_members(tmp_path, rsa_key):
    p = tmp_path / "k.pem"
    _write_pem(p, rsa_key, True)
    jwks = KeyStore.from_files(str(p), []).jwks()
    (k,) = jwks["keys"]
    assert {"kty", "n", "e", "kid", "alg", "use"} <= set(k)
    assert (k["kty"], k["alg"], k["use"]) == ("RSA", "RS256", "sig")


def test_rejects_keys_under_2048_bits(tmp_path):
    p = tmp_path / "weak.pem"
    _write_pem(p, rsa.generate_private_key(65537, 1024), True)
    with pytest.raises(RuntimeError, match="2048"):
        KeyStore.from_files(str(p), [])


def test_two_keys_published_during_rotation(tmp_path, rsa_key):
    priv, pub = tmp_path / "k1.pem", tmp_path / "k2.pub"
    other = rsa.generate_private_key(65537, 2048)
    _write_pem(priv, rsa_key, True)
    _write_pem(pub, other.public_key(), False)
    ks = KeyStore.from_files(str(priv), [str(pub)])
    assert len(ks.jwks()["keys"]) == 2
    assert ks.active.kid == thumbprint_kid(rsa_key.public_key())
