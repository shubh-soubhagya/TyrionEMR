from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.context import get_request_id
from app.domain.clock import Clock


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_clock(request: Request) -> Clock:
    return request.app.state.clock


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """One session per request. Services own commit/rollback boundaries (LLD §16)."""
    async with request.app.state.sessionmaker() as session:
        yield session


# ---- service providers (one instance per request, sharing the request's session) ----------------
from typing import Annotated  # noqa: E402

from fastapi import Depends  # noqa: E402

from app.services.patients import PatientService  # noqa: E402

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_patient_service(request: Request, session: SessionDep) -> PatientService:
    return PatientService(session, request.app.state.settings, request.app.state.clock)


PatientSvc = Annotated[PatientService, Depends(get_patient_service)]


from app.services.allergies import AllergyService  # noqa: E402
from app.services.conditions import ConditionService  # noqa: E402
from app.services.medications import MedicationService  # noqa: E402


def get_condition_service(request: Request, session: SessionDep) -> ConditionService:
    return ConditionService(session, request.app.state.settings, request.app.state.clock)


def get_medication_service(request: Request, session: SessionDep) -> MedicationService:
    return MedicationService(session, request.app.state.settings, request.app.state.clock)


def get_allergy_service(session: SessionDep) -> AllergyService:
    return AllergyService(session)


ConditionSvc = Annotated[ConditionService, Depends(get_condition_service)]
MedicationSvc = Annotated[MedicationService, Depends(get_medication_service)]
AllergySvc = Annotated[AllergyService, Depends(get_allergy_service)]


from app.services.encounters import EncounterService  # noqa: E402


def get_encounter_service(request: Request, session: SessionDep) -> EncounterService:
    return EncounterService(
        session, request.app.state.settings, request.app.state.clock,
        directory=request.app.state.clinician_directory,
        authorization=request.headers.get("authorization", ""),      # the caller's own token, forwarded to /auth/me
        request_id=get_request_id())


EncounterSvc = Annotated[EncounterService, Depends(get_encounter_service)]


from app.services.internal import InternalService  # noqa: E402


def get_internal_service(request: Request, session: SessionDep) -> InternalService:
    return InternalService(session, request.app.state.settings, request.app.state.clock)


InternalSvc = Annotated[InternalService, Depends(get_internal_service)]
