from datetime import timedelta

from fastapi import Response

from app.api.cookies import clear_refresh_cookie, set_refresh_cookie
from tests.conftest import make_settings


def test_set_cookie_flags(clock):
    r = Response()
    set_refresh_cookie(r, "tok", clock() + timedelta(days=7), make_settings(), clock)
    h = r.headers["set-cookie"].lower()
    assert h.startswith("nephro_rt=tok")
    assert "httponly" in h and "secure" in h and "samesite=strict" in h
    assert "path=/api/auth" in h and "domain" not in h
    assert f"max-age={7 * 86400}" in h


def test_secure_flag_is_configurable(clock):
    r = Response()
    set_refresh_cookie(r, "tok", clock() + timedelta(days=1), make_settings(cookie_secure=False), clock)
    assert "secure" not in r.headers["set-cookie"].lower()


def test_clear_cookie():
    r = Response()
    clear_refresh_cookie(r, make_settings())
    h = r.headers["set-cookie"].lower()
    assert "max-age=0" in h and "path=/api/auth" in h and "httponly" in h and "samesite=strict" in h
