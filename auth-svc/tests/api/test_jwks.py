import json

import pytest
from jwt.algorithms import RSAAlgorithm

from app.core.security import verify_access_token
from tests.conftest import GOOD_PASSWORD

pytestmark = pytest.mark.api


async def test_jwks_is_public_cacheable_and_verifies_a_fresh_token(client, make_user, clock):
    await make_user()
    login = await client.post("/auth/login", json={"email": "dr.rao@nephrocare.demo", "password": GOOD_PASSWORD})
    token = login.json()["access_token"]

    r = await client.get("/.well-known/jwks.json")
    assert r.status_code == 200 and r.headers["cache-control"] == "public, max-age=300"
    (key,) = r.json()["keys"]
    assert {"kty", "use", "alg", "kid", "n", "e"} <= set(key)
    assert "d" not in key and "p" not in key and "q" not in key        # never any private material

    # what a verifier (gateway / another service) does: build keys from the published JWKS only
    public = {key["kid"]: RSAAlgorithm.from_jwk(json.dumps(key))}
    claims = verify_access_token(token, public, issuer="nephro-auth", audience="nephro-api",
                                 now=clock().timestamp())
    assert claims.role == "clinician"
