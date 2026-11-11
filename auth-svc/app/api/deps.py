from fastapi import Request

from app.core.config import Settings
from app.domain.clock import Clock
from app.services.auth_service import AuthService


def get_auth_service(request: Request) -> AuthService:
    return request.app.state.auth_service


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_clock(request: Request) -> Clock:
    return request.app.state.clock
