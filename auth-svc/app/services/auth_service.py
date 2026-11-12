"""Signup, login, refresh, logout, me. Transactions live here (LLD §20.6).

Logging rule: never log emails, passwords, tokens or cookies. Only user_id/family_id and outcomes.
"""
from __future__ import annotations

import logging
import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum, auto
from typing import TypedDict

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import metrics
from app.core.config import Settings
from app.core.context import get_request_id
from app.core.errors import (
    AccountDisabled,
    AccountLocked,
    EmailTaken,
    InvalidCredentials,
    NotFound,
    PasswordPolicyError,
    RefreshExpired,
    RefreshInvalid,
    RefreshRace,
    RefreshReused,
    ServiceBusy,
    SignupDisabled,
)
from app.domain.clock import Clock
from app.domain.password_policy import Violation, check_password
from app.models import RefreshToken, User
from app.repositories.auth_event_repository import AuthEventRepository
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.repositories.user_repository import UserRepository
from app.schemas.auth import LoginIn, SignupIn
from app.services.password_hasher import PasswordHasherService
from app.services.token_service import TokenService

log = logging.getLogger("auth")


@dataclass(frozen=True)
class SessionResult:
    user: User
    access_token: str
    expires_in: int
    raw_refresh: str
    refresh_expires_at: datetime


class RefreshOutcome(Enum):
    OK = auto()
    INVALID = auto()
    EXPIRED = auto()
    REUSED = auto()
    RACE = auto()


class _Who(TypedDict):
    """Who is asking: recorded in the audit trail."""

    ip: str | None
    user_agent: str | None


def _trim(user_agent: str | None) -> str | None:
    return user_agent[:256] if user_agent else None


class AuthService:
    def __init__(
        self,
        sm: async_sessionmaker[AsyncSession],
        users: UserRepository,
        refresh_tokens: RefreshTokenRepository,
        hasher: PasswordHasherService,
        tokens: TokenService,
        settings: Settings,
        common_passwords: frozenset[str],
        clock: Clock,
        events: AuthEventRepository | None = None,
    ) -> None:
        self._sm, self._users, self._rt = sm, users, refresh_tokens
        self._hasher, self._tokens, self._s = hasher, tokens, settings
        self._common, self._clock = common_passwords, clock
        self._events = events or AuthEventRepository()

    # ----------------------------------------------------------- audit trail
    def _event(
        self, session: AsyncSession, event: str, outcome: str, *, user_id: uuid.UUID | None = None,
        family_id: uuid.UUID | None = None, ip: str | None = None, user_agent: str | None = None,
    ) -> None:
        """Adds an audit row to the caller's transaction, so it commits with the change it records.
        Never takes an email, password or token: the table has no such columns."""
        self._events.add(session, at=self._clock(), event=event, outcome=outcome, user_id=user_id,
                         family_id=family_id, request_id=get_request_id(), ip=ip, user_agent=user_agent)

    async def _event_alone(self, event: str, outcome: str, **fields) -> None:
        """For failures that have no transaction of their own: a short transaction just for the event."""
        async with self._sm() as session, session.begin():
            self._event(session, event, outcome, **fields)

    # ---------------------------------------------------------------- signup
    async def signup(self, data: SignupIn, user_agent: str | None, ip: str | None = None) -> SessionResult:
        who: _Who = {"ip": ip, "user_agent": user_agent}
        if not self._s.enable_public_signup:
            metrics.AUTH_SIGNUP.labels("disabled").inc()
            log.info("auth.signup.rejected", extra={"reason": "disabled"})
            await self._event_alone("signup", "disabled", **who)
            raise SignupDisabled()

        violations = check_password(data.password, data.email, self._common)
        if violations:
            metrics.AUTH_SIGNUP.labels("policy").inc()
            log.info("auth.signup.rejected", extra={"reason": "policy"})
            await self._event_alone("signup", "policy", **who)
            raise PasswordPolicyError(details=[
                {"field": "password", "code": v.code, "message": v.message} for v in violations])

        # Hash BEFORE opening the transaction: no DB connection is held during the slow hash.
        password_hash = await self._hasher.hash(data.password)
        now = self._clock()
        user = User(id=uuid.uuid4(), email=data.email, password_hash=password_hash,
                    full_name=data.full_name, role="clinician",   # role is server-assigned, never from input
                    created_at=now, updated_at=now)
        try:
            async with self._sm() as session, session.begin():
                await self._users.add(session, user)
                await self._users.register_success(session, user, None, now)
                raw, rt_exp, family_id = await self._start_session(session, user, user_agent, now)
                self._event(session, "signup", "success", user_id=user.id, family_id=family_id, **who)
        except IntegrityError as exc:
            metrics.AUTH_SIGNUP.labels("email_taken").inc()
            log.info("auth.signup.rejected", extra={"reason": "email_taken"})
            await self._event_alone("signup", "email_taken", **who)
            raise EmailTaken() from exc

        access, ttl = self._tokens.issue_access_token(user)
        metrics.AUTH_SIGNUP.labels("success").inc()
        log.info("auth.signup.success", extra={"user_id": str(user.id)})
        return SessionResult(user, access, ttl, raw, rt_exp)

    # ----------------------------------------------------------------- login
    def _locked_error(self, until: datetime | None, now: datetime) -> Exception:
        """429 ACCOUNT_LOCKED, or the generic 401 when LOCKOUT_REVEAL=false."""
        if self._s.lockout_reveal and until is not None:
            return AccountLocked(retry_after=max(1, math.ceil((until - now).total_seconds())))
        return InvalidCredentials()

    async def _release(self, user_id: uuid.UUID) -> None:
        async with self._sm() as session, session.begin():
            await self._users.release_attempt(session, user_id)

    async def _reserve_or_lock(
        self, user: User, event: str, now: datetime, who: _Who
    ) -> tuple[int | None, datetime | None]:
        """Reserve an attempt. No row back means the account is locked, or every attempt is already taken
        by in-flight requests: lock it (idempotent) and report the deadline."""
        locked_until: datetime | None = None
        async with self._sm() as session, session.begin():
            count = await self._users.reserve_attempt(
                session, user.id, self._s.login_max_attempts, self._s.login_failure_window_minutes, now)
            if count is None:
                locked_until, flipped = await self._users.lock_out(
                    session, user.id, self._s.login_lock_minutes, now)
                if flipped:
                    self._event(session, "lockout", "locked", user_id=user.id, **who)
                self._event(session, event, "locked", user_id=user.id, **who)
        return count, locked_until

    async def _record_bad_password(self, user: User, event: str, count: int, now: datetime, who: _Who) -> None:
        """One transaction: lock the account if this was the last allowed attempt, and record the failure."""
        locked_until: datetime | None = None
        flipped = False
        async with self._sm() as session, session.begin():
            if count >= self._s.login_max_attempts:
                locked_until, flipped = await self._users.lock_out(
                    session, user.id, self._s.login_lock_minutes, now)
                if flipped:
                    self._event(session, "lockout", "locked", user_id=user.id, **who)
            self._event(session, event, "bad_password", user_id=user.id, **who)
        if flipped:
            log.warning("auth.account.locked", extra={
                "user_id": str(user.id), "until": locked_until.isoformat() if locked_until else None})

    async def login(self, data: LoginIn, user_agent: str | None, ip: str | None = None) -> SessionResult:
        """Attempt reservation (LLD §19.2). An attempt is reserved atomically BEFORE the password is
        verified, so N parallel guesses can only ever try ``login_max_attempts`` passwords. A correct
        password re-checks the lock under a row lock, so it can never succeed after the account locked."""
        now = self._clock()
        who: _Who = {"ip": ip, "user_agent": user_agent}
        async with self._sm() as session:
            user = await self._users.get_by_email(session, data.email)

        if user is None:
            await self._hasher.verify_dummy(data.password)   # equalize timing for unknown emails
            metrics.AUTH_LOGIN.labels("unknown_user").inc()
            log.info("auth.login.failure", extra={"reason": "unknown_user"})
            await self._event_alone("login", "unknown_user", **who)
            raise InvalidCredentials()

        # Fast path: a locked account is rejected before any hashing (no signal, no CPU cost)
        if user.locked_until and user.locked_until > now:
            metrics.AUTH_LOGIN.labels("locked").inc()
            log.info("auth.login.failure", extra={"reason": "locked", "user_id": str(user.id)})
            await self._event_alone("login", "locked", user_id=user.id, **who)
            raise self._locked_error(user.locked_until, now)

        count, locked_until = await self._reserve_or_lock(user, "login", now, who)
        if count is None:
            metrics.AUTH_LOGIN.labels("locked").inc()
            log.info("auth.login.failure", extra={"reason": "locked", "user_id": str(user.id)})
            raise self._locked_error(locked_until, now)

        try:
            correct = await self._hasher.verify(user.password_hash, data.password)
        except ServiceBusy:
            await self._release(user.id)        # overload must not push a user toward lockout
            metrics.AUTH_LOGIN.labels("busy").inc()
            raise

        if not correct:
            await self._record_bad_password(user, "login", count, now, who)
            metrics.AUTH_LOGIN.labels("bad_password").inc()
            log.info("auth.login.failure", extra={"reason": "bad_password", "user_id": str(user.id)})
            raise InvalidCredentials()   # the 5th failure still returns 401; the next attempt sees 429

        if not user.is_active:
            async with self._sm() as session, session.begin():   # a correct password is not a failed attempt
                await self._users.release_attempt(session, user.id)
                self._event(session, "login", "disabled", user_id=user.id, **who)
            metrics.AUTH_LOGIN.labels("disabled").inc()
            log.info("auth.login.failure", extra={"reason": "disabled", "user_id": str(user.id)})
            raise AccountDisabled()

        rehash = self._hasher.needs_rehash(user.password_hash)
        try:
            new_hash = await self._hasher.hash(data.password) if rehash else None
        except ServiceBusy:
            await self._release(user.id)
            raise

        fresh: User | None
        locked_now: datetime | None = None
        async with self._sm() as session, session.begin():
            fresh = await self._users.get_for_update(session, user.id)
            if fresh is not None and fresh.locked_until and fresh.locked_until > now:
                locked_now = fresh.locked_until           # another request locked it while we verified
                self._event(session, "login", "locked", user_id=user.id, **who)
            elif fresh is not None:
                await self._users.register_success(session, fresh, new_hash, now)
                raw, rt_exp, family_id = await self._start_session(session, fresh, user_agent, now)
                self._event(session, "login", "success", user_id=fresh.id, family_id=family_id, **who)
        if fresh is None:
            raise InvalidCredentials()
        if locked_now is not None:
            metrics.AUTH_LOGIN.labels("locked").inc()
            log.info("auth.login.failure", extra={"reason": "locked", "user_id": str(user.id)})
            raise self._locked_error(locked_now, now)
        access, ttl = self._tokens.issue_access_token(fresh)
        metrics.AUTH_LOGIN.labels("success").inc()
        log.info("auth.login.success", extra={"user_id": str(fresh.id), "rehashed": rehash})
        return SessionResult(fresh, access, ttl, raw, rt_exp)

    # ------------------------------------------------------- change password
    async def change_password(
        self, user_id: uuid.UUID, current_password: str, new_password: str, raw_refresh: str | None,
        user_agent: str | None, ip: str | None = None,
    ) -> SessionResult | None:
        """Verifies the current password (it counts toward lockout exactly like a login), applies the
        policy, stores the new hash, revokes EVERY other session of the user and keeps this one by
        rotating its refresh token. Returns the rotated session, or None if the caller had no valid
        refresh cookie (then all sessions are revoked and nothing is issued)."""
        now = self._clock()
        who: _Who = {"ip": ip, "user_agent": user_agent}
        async with self._sm() as session:
            user = await self._users.get(session, user_id)
        if user is None:
            raise NotFound()
        if not user.is_active:
            raise AccountDisabled()

        violations: list[Violation] = check_password(new_password, user.email, self._common)
        if new_password == current_password:
            violations.append(Violation("SAME_AS_CURRENT", "Must differ from the current password."))
        if violations:
            await self._event_alone("password_change", "policy", user_id=user.id, **who)
            raise PasswordPolicyError(details=[
                {"field": "new_password", "code": v.code, "message": v.message} for v in violations])

        if user.locked_until and user.locked_until > now:
            await self._event_alone("password_change", "locked", user_id=user.id, **who)
            raise self._locked_error(user.locked_until, now)
        count, locked_until = await self._reserve_or_lock(user, "password_change", now, who)
        if count is None:
            raise self._locked_error(locked_until, now)

        try:
            correct = await self._hasher.verify(user.password_hash, current_password)
        except ServiceBusy:
            await self._release(user.id)
            raise
        if not correct:
            await self._record_bad_password(user, "password_change", count, now, who)
            raise InvalidCredentials("Current password is incorrect.")

        try:
            new_hash = await self._hasher.hash(new_password)
        except ServiceBusy:
            await self._release(user.id)
            raise

        new_raw: str | None = None
        new_exp = now
        locked_now: datetime | None = None
        fresh: User | None
        async with self._sm() as session, session.begin():
            fresh = await self._users.get_for_update(session, user.id)
            if fresh is not None and fresh.locked_until and fresh.locked_until > now:
                locked_now = fresh.locked_until
                self._event(session, "password_change", "locked", user_id=user.id, **who)
            elif fresh is not None:
                await self._users.set_password(session, fresh, new_hash, now)
                keep_family: uuid.UUID | None = None
                row = (await self._rt.get_by_hash_for_update(session, self._tokens.hash_refresh(raw_refresh))
                       if raw_refresh else None)
                if (row is not None and row.user_id == fresh.id and row.revoked_at is None
                        and row.expires_at > now and row.family_expires_at > now):
                    new_raw, new_exp = await self._rotate(session, row, user_agent, now)
                    keep_family = row.family_id
                revoked = await self._rt.revoke_user_sessions(
                    session, fresh.id, "password_changed", now, except_family_id=keep_family)
                self._event(session, "password_change", "success", user_id=fresh.id, family_id=keep_family, **who)
        if fresh is None:
            raise NotFound()
        if locked_now is not None:
            raise self._locked_error(locked_now, now)
        log.info("auth.password.changed", extra={"user_id": str(fresh.id), "revoked_count": revoked,
                                                "kept_session": new_raw is not None})
        if new_raw is None:
            return None
        access, ttl = self._tokens.issue_access_token(fresh)
        return SessionResult(fresh, access, ttl, new_raw, new_exp)

    # --------------------------------------------------------------- refresh
    async def refresh(self, raw: str, user_agent: str | None, ip: str | None = None) -> SessionResult:
        now = self._clock()
        outcome = RefreshOutcome.INVALID
        user: User | None = None
        new_raw = ""
        new_exp = now
        family_id: uuid.UUID | None = None
        owner_id: uuid.UUID | None = None
        revoked_count = 0

        async with self._sm() as session, session.begin():
            row = await self._rt.get_by_hash_for_update(session, self._tokens.hash_refresh(raw))
            if row is None:
                outcome = RefreshOutcome.INVALID
            else:
                family_id, owner_id = row.family_id, row.user_id
                if row.revoked_at is not None:
                    if row.revoked_reason != "rotated":
                        # Revoked by logout, an earlier reuse detection or user deactivation: the
                        # session is simply over. Not theft, so no family revocation and no alert.
                        outcome = RefreshOutcome.INVALID
                    elif (now - row.revoked_at).total_seconds() <= self._s.refresh_reuse_grace_s:
                        outcome = RefreshOutcome.RACE      # change nothing, issue nothing
                    else:
                        # A token that was legitimately rotated away is replayed: someone kept a copy
                        revoked_count = await self._rt.revoke_family(session, row.family_id, "reuse_detected", now)
                        outcome = RefreshOutcome.REUSED
                        self._event(session, "refresh", "reuse_detected", user_id=row.user_id,
                                    family_id=row.family_id, ip=ip, user_agent=user_agent)
                elif row.expires_at <= now or row.family_expires_at <= now:
                    outcome = RefreshOutcome.EXPIRED
                else:
                    user = await self._users.get(session, row.user_id)
                    if user is None or not user.is_active:
                        await self._rt.revoke_family(session, row.family_id, "user_inactive", now)
                        outcome = RefreshOutcome.INVALID
                    else:
                        new_raw, new_exp = await self._rotate(session, row, user_agent, now)
                        outcome = RefreshOutcome.OK
        # The transaction has COMMITTED here, including any family revocation. The error is raised
        # only now: raising inside the block would roll the revocation back (LLD §19.3 / §20.6).

        metrics.AUTH_REFRESH.labels(outcome.name.lower()).inc()
        if outcome is RefreshOutcome.OK and user is not None:
            access, ttl = self._tokens.issue_access_token(user)
            log.info("auth.refresh.success", extra={"user_id": str(user.id), "family_id": str(family_id)})
            return SessionResult(user, access, ttl, new_raw, new_exp)
        if outcome is RefreshOutcome.REUSED:
            metrics.AUTH_REUSE.inc()
            log.warning("auth.refresh.reuse_detected", extra={
                "user_id": str(owner_id), "family_id": str(family_id), "revoked_count": revoked_count})
        else:
            log.info("auth.refresh.failure", extra={"reason": outcome.name.lower()})
        errors = {RefreshOutcome.INVALID: RefreshInvalid, RefreshOutcome.EXPIRED: RefreshExpired,
                  RefreshOutcome.REUSED: RefreshReused, RefreshOutcome.RACE: RefreshRace}
        raise errors[outcome]()

    # --------------------------------------------------------------- logout
    async def logout(self, raw: str | None, user_agent: str | None = None, ip: str | None = None) -> None:
        """Idempotent: missing, unknown or already-revoked cookies all succeed."""
        if not raw:
            return
        now = self._clock()
        revoked = 0
        user_id: uuid.UUID | None = None
        async with self._sm() as session, session.begin():
            row = await self._rt.get_by_hash_for_update(session, self._tokens.hash_refresh(raw))
            if row is not None:
                user_id = row.user_id
                revoked = await self._rt.revoke_family(session, row.family_id, "logout", now)
                self._event(session, "logout", "success", user_id=row.user_id, family_id=row.family_id,
                            ip=ip, user_agent=user_agent)
        log.info("auth.logout", extra={"user_id": str(user_id) if user_id else None, "revoked_count": revoked})

    # ------------------------------------------------------------------- me
    async def me(self, user_id: uuid.UUID) -> User:
        async with self._sm() as session:
            user = await self._users.get(session, user_id)
        if user is None:
            raise NotFound()
        if not user.is_active:
            raise AccountDisabled()
        return user

    # -------------------------------------------------------------- helpers
    async def _rotate(
        self, session: AsyncSession, row: RefreshToken, user_agent: str | None, now: datetime
    ) -> tuple[str, datetime]:
        """Single-use rotation: issue the next token in the same family and mark this one rotated."""
        new_raw, new_hash = self._tokens.new_refresh_secret()
        new_exp = min(now + timedelta(days=self._s.refresh_token_ttl_days), row.family_expires_at)
        new = RefreshToken(
            id=uuid.uuid4(), user_id=row.user_id, family_id=row.family_id, token_hash=new_hash,
            expires_at=new_exp, family_expires_at=row.family_expires_at,
            user_agent=_trim(user_agent), created_at=now)
        await self._rt.add(session, new)   # flush, so new.id exists
        row.revoked_at, row.revoked_reason, row.replaced_by_id = now, "rotated", new.id
        return new_raw, new_exp

    async def _start_session(
        self, session: AsyncSession, user: User, user_agent: str | None, now: datetime
    ) -> tuple[str, datetime, uuid.UUID]:
        raw, h = self._tokens.new_refresh_secret()
        family_id = uuid.uuid4()
        family_exp = now + timedelta(days=self._s.session_max_days)
        exp = min(now + timedelta(days=self._s.refresh_token_ttl_days), family_exp)
        await self._rt.add(session, RefreshToken(
            id=uuid.uuid4(), user_id=user.id, family_id=family_id, token_hash=h,
            expires_at=exp, family_expires_at=family_exp, user_agent=_trim(user_agent), created_at=now))
        return raw, exp, family_id
