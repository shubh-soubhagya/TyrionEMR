"""Shared bootstrap for the operator CLI commands."""
from __future__ import annotations

import argparse
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.core.errors import AppError
from app.db.session import create_engine, create_sessionmaker
from app.domain.clock import utcnow
from app.domain.password_policy import load_common_passwords
from app.repositories.auth_event_repository import AuthEventRepository
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.repositories.user_repository import UserRepository
from app.schemas.auth import _normalize_email
from app.services.account_admin import AccountAdminService
from app.services.password_hasher import PasswordHasherService


@asynccontextmanager
async def admin_service() -> AsyncIterator[AccountAdminService]:
    from app.core.config import get_settings

    s = get_settings()
    engine = create_engine(s)
    try:
        yield AccountAdminService(
            create_sessionmaker(engine), UserRepository(), RefreshTokenRepository(), AuthEventRepository(),
            PasswordHasherService(s), load_common_passwords(), utcnow)
    finally:
        await engine.dispose()


def email_parser(prog: str, description: str) -> argparse.ArgumentParser:
    """--email is REQUIRED: argparse exits with status 2 and a usage message if it is missing."""
    parser = argparse.ArgumentParser(prog=prog, description=description)
    parser.add_argument("--email", required=True, help="the clinician's email address")
    return parser


def parse_email(raw: str) -> str:
    return _normalize_email(raw)


def explain(exc: AppError) -> str:
    detail = "; ".join(d["message"] for d in exc.details) if exc.details else ""
    return f"{exc.message} {detail}".strip()
