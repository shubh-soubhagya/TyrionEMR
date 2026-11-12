"""Operator actions on accounts (used by the CLI tools; there is no admin API, ADR-018).

Every action writes its audit event in the same transaction as the change it records."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import NotFound, PasswordPolicyError
from app.domain.clock import Clock
from app.domain.password_policy import check_password
from app.models import User
from app.repositories.auth_event_repository import AuthEventRepository
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.repositories.user_repository import UserRepository
from app.services.password_hasher import PasswordHasherService

log = logging.getLogger("auth.admin")


@dataclass(frozen=True)
class AdminResult:
    sessions_revoked: int = 0
    was_locked: bool = False
    already_inactive: bool = False


class AccountAdminService:
    def __init__(
        self,
        sm: async_sessionmaker[AsyncSession],
        users: UserRepository,
        refresh_tokens: RefreshTokenRepository,
        events: AuthEventRepository,
        hasher: PasswordHasherService,
        common_passwords: frozenset[str],
        clock: Clock,
    ) -> None:
        self._sm, self._users, self._rt, self._events = sm, users, refresh_tokens, events
        self._hasher, self._common, self._clock = hasher, common_passwords, clock

    async def _user(self, session: AsyncSession, email: str) -> User:
        user = await self._users.get_by_email_for_update(session, email)
        if user is None:
            raise NotFound("No user with that email.")
        return user

    def _event(self, session: AsyncSession, event: str, user: User, outcome: str = "success") -> None:
        self._events.add(session, at=self._clock(), event=event, outcome=outcome, user_id=user.id)

    async def set_password(self, email: str, password: str) -> AdminResult:
        """Same policy as signup. Clears any lock and signs the user out everywhere."""
        violations = check_password(password, email, self._common)
        if violations:
            raise PasswordPolicyError(details=[
                {"field": "password", "code": v.code, "message": v.message} for v in violations])
        new_hash = await self._hasher.hash(password)
        now = self._clock()
        async with self._sm() as session, session.begin():
            user = await self._user(session, email)
            await self._users.set_password(session, user, new_hash, now)
            revoked = await self._rt.revoke_user_sessions(session, user.id, "password_changed", now)
            self._event(session, "password_set", user)
        log.info("auth.admin.password_set", extra={"user_id": str(user.id), "revoked_count": revoked})
        return AdminResult(sessions_revoked=revoked)

    async def unlock(self, email: str) -> AdminResult:
        now = self._clock()
        async with self._sm() as session, session.begin():
            user = await self._user(session, email)
            was_locked = await self._users.unlock(session, user, now)
            self._event(session, "unlock", user)
        log.info("auth.admin.unlock", extra={"user_id": str(user.id), "was_locked": was_locked})
        return AdminResult(was_locked=was_locked)

    async def deactivate(self, email: str) -> AdminResult:
        """Disables sign-in and signs the user out everywhere. Idempotent."""
        now = self._clock()
        async with self._sm() as session, session.begin():
            user = await self._user(session, email)
            already = not user.is_active
            await self._users.set_active(session, user, False, now)
            revoked = await self._rt.revoke_user_sessions(session, user.id, "user_inactive", now)
            self._event(session, "deactivation", user)
        log.info("auth.admin.deactivate", extra={"user_id": str(user.id), "revoked_count": revoked})
        return AdminResult(sessions_revoked=revoked, already_inactive=already)

    async def revoke_sessions(self, email: str) -> AdminResult:
        """Sign the user out everywhere (access tokens already issued expire within 15 minutes)."""
        now = self._clock()
        async with self._sm() as session, session.begin():
            user = await self._user(session, email)
            revoked = await self._rt.revoke_user_sessions(session, user.id, "logout", now)
            self._event(session, "sessions_revoked", user)
        log.info("auth.admin.revoke_sessions", extra={"user_id": str(user.id), "revoked_count": revoked})
        return AdminResult(sessions_revoked=revoked)
