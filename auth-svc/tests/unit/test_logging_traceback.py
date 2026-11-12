"""Item 8: unhandled exceptions are logged with their stack, without messages or frame locals."""
import json
import logging

import httpx
import pytest
from fastapi import FastAPI

from app.core.common_setup import install_common_middleware
from app.core.logging import JsonFormatter

SECRET_MESSAGE = "SECRET-MESSAGE-user@example.org-token-abc123"
SECRET_LOCAL = "SECRET-LOCAL-hunter2hunter2"


def explode_inner():
    local_password = SECRET_LOCAL            # a frame local that must never reach the logs
    raise KeyError(SECRET_MESSAGE) if local_password else None


def explode_outer():
    try:
        explode_inner()
    except KeyError as exc:
        raise RuntimeError(f"wrapped: {SECRET_MESSAGE}") from exc


@pytest.fixture
def client():
    app = FastAPI()
    install_common_middleware(app)

    @app.get("/boom")
    async def boom():
        explode_outer()

    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                             base_url="http://t")


async def test_stack_is_logged_without_messages_or_locals(client, caplog):
    caplog.set_level(logging.INFO)
    async with client as c:
        r = await c.get("/boom")
    assert r.status_code == 500 and r.json()["error"]["code"] == "INTERNAL_ERROR"

    fmt = JsonFormatter("auth-svc")
    lines = [json.loads(fmt.format(rec)) for rec in caplog.records if rec.exc_info]
    assert len(lines) == 1
    line = lines[0]

    assert "explode_outer" in [f["function"] for f in line["stack"]]                  # where it surfaced
    assert "explode_inner" in [f["function"] for f in line["cause_stack"]]            # where it originated
    assert all(isinstance(f["line"], int) and f["file"] for f in line["stack"])
    assert line["exc_type"] == "RuntimeError" and line["exc_chain"] == ["RuntimeError", "KeyError"]
    assert line["request_id"] == r.headers["x-request-id"]

    raw = fmt.format([rec for rec in caplog.records if rec.exc_info][0])
    for secret in (SECRET_MESSAGE, SECRET_LOCAL, "user@example.org", "hunter2", "abc123"):
        assert secret not in raw, f"leaked: {secret}"


def test_paths_are_shortened_to_the_last_three_segments():
    from app.core.logging import _short_path
    assert _short_path(r"C:\Users\hp\Desktop\TyrionEMR\auth-svc\app\core\x.py") == "app/core/x.py"
    assert _short_path("/opt/venv/lib/python3.12/site-packages/app/core/x.py") == "app/core/x.py"
    assert _short_path("x.py") == "x.py"
