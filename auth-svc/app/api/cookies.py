"""Refresh-cookie helpers (LLD §19.7): HttpOnly, SameSite=Strict, Path=/api/auth, no Domain."""
from __future__ import annotations

from datetime import datetime

from fastapi import Response

from app.core.config import Settings
from app.domain.clock import Clock


def set_refresh_cookie(resp: Response, raw: str, expires_at: datetime, s: Settings, clock: Clock) -> None:
    max_age = max(0, int((expires_at - clock()).total_seconds()))
    resp.set_cookie(s.refresh_cookie_name, raw, max_age=max_age, path=s.refresh_cookie_path,
                    secure=s.cookie_secure, httponly=True, samesite="strict")


def clear_refresh_cookie(resp: Response, s: Settings) -> None:
    resp.delete_cookie(s.refresh_cookie_name, path=s.refresh_cookie_path,
                       secure=s.cookie_secure, httponly=True, samesite="strict")
