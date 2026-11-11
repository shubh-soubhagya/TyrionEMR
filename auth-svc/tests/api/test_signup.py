import pytest

from tests.conftest import GOOD_PASSWORD, set_cookie_headers, sql

pytestmark = pytest.mark.api
BODY = {"full_name": "Dr. Priya Sharma", "email": "priya.sharma@clinic.test", "password": GOOD_PASSWORD}


async def test_signup_returns_201_token_user_and_cookie(client):
    r = await client.post("/auth/signup", json=BODY)
    assert r.status_code == 201
    j = r.json()
    assert j["token_type"] == "Bearer" and j["expires_in"] == 900 and j["access_token"]
    assert j["user"]["email"] == "priya.sharma@clinic.test" and j["user"]["role"] == "clinician"
    assert j["user"]["last_login_at"] is not None
    assert "password" not in r.text.lower().replace("password_", "")
    assert r.headers["cache-control"] == "no-store" and r.headers["pragma"] == "no-cache"
    (cookie,) = set_cookie_headers(r)
    low = cookie.lower()
    assert "httponly" in low and "secure" in low and "samesite=strict" in low
    assert "path=/api/auth" in low and "domain" not in low


async def test_role_is_always_clinician_even_if_payload_asks_for_admin(client, app):
    r = await client.post("/auth/signup", json={**BODY, "role": "admin"})
    assert r.status_code == 201 and r.json()["user"]["role"] == "clinician"
    assert (await sql(app, "SELECT role FROM users"))[0][0] == "clinician"


async def test_password_is_stored_as_argon2id_never_plaintext(client, app):
    await client.post("/auth/signup", json=BODY)
    stored = (await sql(app, "SELECT password_hash FROM users"))[0][0]
    assert stored.startswith("$argon2id$") and GOOD_PASSWORD not in stored


async def test_refresh_token_is_stored_only_as_sha256(client, app):
    r = await client.post("/auth/signup", json=BODY)
    raw = set_cookie_headers(r)[0].split(";")[0].split("=", 1)[1]
    (stored,) = (await sql(app, "SELECT token_hash FROM refresh_tokens"))[0]
    assert stored != raw and len(stored) == 64


async def test_duplicate_email_with_different_case_is_409(client):
    await client.post("/auth/signup", json=BODY)
    r = await client.post("/auth/signup", json={**BODY, "email": "Priya.Sharma@Clinic.TEST"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "EMAIL_TAKEN"


async def test_password_rule_failures_are_listed_with_codes(client):
    r = await client.post("/auth/signup", json={**BODY, "password": "short"})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "VALIDATION_ERROR"
    codes = {d["code"] for d in err["details"]}
    assert {"TOO_SHORT", "NEEDS_DIGIT"} <= codes
    assert all(d["field"] == "password" for d in err["details"])
    assert "short" not in r.text.replace("TOO_SHORT", "")      # the submitted password is never echoed


async def test_common_password_and_email_name_are_rejected(client):
    r = await client.post("/auth/signup", json={**BODY, "password": "Password1234"})
    assert "TOO_COMMON" in {d["code"] for d in r.json()["error"]["details"]}
    r = await client.post("/auth/signup", json={**BODY, "password": "priya.sharma-2026x"})
    assert "CONTAINS_EMAIL" in {d["code"] for d in r.json()["error"]["details"]}


async def test_malformed_email_is_422(client):
    r = await client.post("/auth/signup", json={**BODY, "email": "not-an-email"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_signup_disabled_returns_403(make_app):
    from tests.conftest import client_for
    app = await make_app(enable_public_signup=False)
    async with client_for(app) as c:
        r = await c.post("/auth/signup", json=BODY)
    assert r.status_code == 403 and r.json()["error"]["code"] == "SIGNUP_DISABLED"
