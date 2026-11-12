"""Item 11: zero-downtime signing-key rotation (LLD 26.2) and the key scripts."""
import shutil
import subprocess
import uuid
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.models import User
from app.services.keystore import KeyStore, SigningKey, thumbprint_kid
from tests.conftest import GOOD_PASSWORD, client_for

ROOT = Path(__file__).resolve().parents[2]
EMAIL = "dr.rao@nephrocare.demo"


def keystore(active, *also_published) -> KeyStore:
    pub = active.public_key()
    published = {thumbprint_kid(pub): pub}
    for key in also_published:
        published[thumbprint_kid(key.public_key())] = key.public_key()
    return KeyStore(SigningKey(thumbprint_kid(pub), active), published)


def kid_of(token):
    return jwt.get_unverified_header(token)["kid"]


@pytest.mark.api
async def test_rotation_keeps_old_tokens_valid_and_new_tokens_use_the_new_kid(make_app, rsa_key):
    k1, k2 = rsa_key, rsa.generate_private_key(public_exponent=65537, key_size=2048)
    kid1, kid2 = thumbprint_kid(k1.public_key()), thumbprint_kid(k2.public_key())
    me = lambda c, t: c.get("/auth/me", headers={"authorization": f"Bearer {t}"})  # noqa: E731

    # step 2: k1 signs, k1 and k2 are both published
    app1 = await make_app(keystore=keystore(k1, k2))
    async with app1.state.sessionmaker() as s, s.begin():
        s.add(User(id=uuid.uuid4(), email=EMAIL, full_name="Dr. Rao", role="clinician",
                   password_hash=await app1.state.hasher.hash(GOOD_PASSWORD),
                   created_at=app1.state.clock(), updated_at=app1.state.clock()))
    async with client_for(app1) as c:
        assert {k["kid"] for k in (await c.get("/.well-known/jwks.json")).json()["keys"]} == {kid1, kid2}
        token1 = (await c.post("/auth/login", json={"email": EMAIL, "password": GOOD_PASSWORD})).json()["access_token"]
        assert kid_of(token1) == kid1                               # still signed with k1
        assert (await me(c, token1)).status_code == 200

    # step 4: k2 signs, k1 stays published
    app2 = await make_app(keystore=keystore(k2, k1), truncate=False)
    async with client_for(app2) as c:
        assert {k["kid"] for k in (await c.get("/.well-known/jwks.json")).json()["keys"]} == {kid1, kid2}
        assert (await me(c, token1)).status_code == 200            # old token still verifies
        token2 = (await c.post("/auth/login", json={"email": EMAIL, "password": GOOD_PASSWORD})).json()["access_token"]
        assert kid_of(token2) == kid2                               # new tokens use the new kid
        assert (await me(c, token2)).status_code == 200

    # step 6: k1 retired
    app3 = await make_app(keystore=keystore(k2), truncate=False)
    async with client_for(app3) as c:
        assert [k["kid"] for k in (await c.get("/.well-known/jwks.json")).json()["keys"]] == [kid2]
        old = await me(c, token1)
        assert old.status_code == 401 and old.json()["error"]["code"] == "UNAUTHENTICATED"
        assert (await me(c, token2)).status_code == 200


@pytest.mark.api
async def test_refresh_tokens_are_unaffected_by_rotation(make_app, rsa_key):
    from tests.conftest import rt_cookie, with_cookie
    k1, k2 = rsa_key, rsa.generate_private_key(public_exponent=65537, key_size=2048)
    app1 = await make_app(keystore=keystore(k1, k2))
    async with app1.state.sessionmaker() as s, s.begin():
        s.add(User(id=uuid.uuid4(), email=EMAIL, full_name="Dr. Rao", role="clinician",
                   password_hash=await app1.state.hasher.hash(GOOD_PASSWORD),
                   created_at=app1.state.clock(), updated_at=app1.state.clock()))
    async with client_for(app1) as c:
        rt = rt_cookie(await c.post("/auth/login", json={"email": EMAIL, "password": GOOD_PASSWORD}))
    app2 = await make_app(keystore=keystore(k2), truncate=False)       # k1 gone entirely
    async with client_for(app2) as c:
        r = await c.post("/auth/refresh", headers=with_cookie(rt))
        assert r.status_code == 200 and kid_of(r.json()["access_token"]) == thumbprint_kid(k2.public_key())


# ------------------------------------------------------------------------------------- scripts
def find_bash():
    for candidate in ("C:/Program Files/Git/bin/bash.exe", "/bin/bash", "/usr/bin/bash"):
        if Path(candidate).exists():
            return candidate
    found = shutil.which("bash")
    return found if found and "system32" not in found.lower() else None


BASH = find_bash()
needs_tools = pytest.mark.skipif(not (BASH and shutil.which("openssl")), reason="bash and openssl are required")


@pytest.fixture
def scripts(tmp_path):
    """A private copy of setup/ so the real keys are never touched."""
    dest = tmp_path / "setup"
    (dest / "keys").mkdir(parents=True)
    for name in ("generate-keys.sh", "rotate-keys.sh"):
        shutil.copy(ROOT / "setup" / name, dest / name)
    return dest


def run(script, *args):
    return subprocess.run([BASH, str(script), *args], capture_output=True, text=True, timeout=120)


@needs_tools
def test_generate_keys_dev_mode_warns(scripts):
    r = run(scripts / "generate-keys.sh")
    assert r.returncode == 0 and "DEVELOPMENT" in r.stdout and "WARNING" in r.stdout
    assert (scripts / "keys" / "jwt_private.pem").exists() and (scripts / "keys" / "jwt_public.pem").exists()


@needs_tools
def test_generate_keys_prod_mode_says_how_to_hand_over_the_key(scripts):
    r = run(scripts / "generate-keys.sh", "--prod")
    assert r.returncode == 0 and "0600" in r.stdout and "10001" in r.stdout
    assert "DEVELOPMENT" not in r.stdout


@needs_tools
def test_generate_keys_rejects_unknown_arguments(scripts):
    assert run(scripts / "generate-keys.sh", "--bogus").returncode == 2


@needs_tools
def test_rotate_keys_creates_the_next_key_and_prints_the_remaining_steps(scripts):
    run(scripts / "generate-keys.sh")
    r = run(scripts / "rotate-keys.sh", "--prod")
    assert r.returncode == 0
    new_private = next((scripts / "keys").glob("jwt_private_*.pem"))
    new_public = next((scripts / "keys").glob("jwt_public_*.pem"))
    out = r.stdout
    assert "JWT_ADDITIONAL_PUBLIC_KEY_PATHS" in out and new_public.name in out
    for step in ("3.", "4.", "5.", "6."):
        assert step in out
    assert "15 minutes + 30 seconds" in out and "5 minutes" in out
    # the printed configuration actually loads: current key signs, the next public key is published
    ks = KeyStore.from_files(str(scripts / "keys" / "jwt_private.pem"), [str(new_public)])
    assert len(ks.jwks()["keys"]) == 2 and new_private.exists()


@needs_tools
def test_rotate_keys_needs_a_current_key(scripts):
    r = run(scripts / "rotate-keys.sh")
    assert r.returncode == 1 and "generate-keys.sh" in r.stderr
