from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.domain.clock import Clock
from app.services.reads import ReadService
from app.services.reports import ReportService


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_clock(request: Request) -> Clock:
    return request.app.state.clock


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """One session per request. Services own commit/rollback boundaries."""
    async with request.app.state.sessionmaker() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_report_service(request: Request, session: SessionDep) -> ReportService:
    s = request.app.state
    return ReportService(session, s.settings, s.clock, s.patients)


def get_read_service(request: Request, session: SessionDep) -> ReadService:
    return ReadService(session, request.app.state.settings)


ReportSvc = Annotated[ReportService, Depends(get_report_service)]
ReadSvc = Annotated[ReadService, Depends(get_read_service)]


def authorization_header(request: Request) -> str:
    """The caller's own bearer token, forwarded to patient-svc (the audit trail shows the real user)."""
    return request.headers.get("authorization", "")


AuthHeader = Annotated[str, Depends(authorization_header)]
