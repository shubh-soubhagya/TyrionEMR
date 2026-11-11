"""Non-negotiable: never log emails, passwords, tokens, cookies or Authorization headers."""
import logging

import pytest

from app.core.logging import JsonFormatter
from tests.conftest import GOOD_PASSWORD, rt_cookie, with_cookie

pytestmark = pytest.mark.api
EMAIL = "dr.rao@nephrocare.demo"
LOCAL_PART = "dr.rao"


def rendered(caplog) -> str:
    fmt = JsonFormatter("auth-svc")
    return "\n".join(fmt.format(r) for r in caplog.records)


async def test_full_session_lifecycle_logs_no_secrets(client, make_user, caplog, clock):
    caplog.set_level(logging.DEBUG)
    await make_user()
    secrets_seen = [EMAIL, LOCAL_PART, GOOD_PASSWORD, "WrongPassword99", "stranger@nephrocare.demo"]

    # success, wrong password, unknown email, signup + duplicate, refresh, reuse, me, logout
    login = await client.post("/auth/login", json={"email": EMAIL, "password": GOOD_PASSWORD})
    await client.post("/auth/login", json={"email": EMAIL, "password": "WrongPassword99"})
    await client.post("/auth/login", json={"email": "stranger@nephrocare.demo", "password": "WrongPassword99"})
    access = login.json()["access_token"]
    rt1 = rt_cookie(login)
    r2 = await client.post("/auth/refresh", headers=with_cookie(rt1))
    rt2 = rt_cookie(r2)
    clock.advance(seconds=11)
    await client.post("/auth/refresh", headers=with_cookie(rt1))          # reuse -> WARN event
    await client.get("/auth/me", headers={"authorization": f"Bearer {access}"})
    await client.post("/auth/logout", headers=with_cookie(rt2))
    await client.post("/auth/signup", json={"full_name": "Dr. New", "email": "new.person@nephrocare.demo",
                                            "password": "Pass-Word-2026x"})
    await client.post("/auth/signup", json={"full_name": "Dr. New", "email": "new.person@nephrocare.demo",
                                            "password": "Pass-Word-2026x"})
    secrets_seen += ["new.person@nephrocare.demo", "Pass-Word-2026x", access, rt1, rt2,
                     login.json()["access_token"][:40]]

    logs = rendered(caplog)
    assert "auth.login.success" in logs and "auth.refresh.reuse_detected" in logs   # the events DO exist
    for secret in secrets_seen:
        assert secret not in logs, f"leaked into logs: {secret[:12]}..."
    assert "Bearer" not in logs and "nephro_rt" not in logs.replace('"nephro_rt"', "")


def test_redaction_masks_sensitive_extras_even_if_a_caller_passes_them(caplog):
    caplog.set_level(logging.INFO)
    logging.getLogger("auth").info("probe", extra={"email": "x@y.z", "password": "hunter2hunter2",
                                                   "payload": {"refresh_token": "abc", "ok": 1}})
    out = rendered(caplog)
    assert "x@y.z" not in out and "hunter2" not in out and '"abc"' not in out
    assert '"ok":1' in out
