from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from email_validator import EmailNotValidError, validate_email
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints


def _normalize_email(value: str) -> str:
    # test_environment=True accepts reserved TLDs such as ".test" (the LLD's own examples use
    # clinic.test); EmailStr would reject them. Deliverability is never checked.
    try:
        result = validate_email(value, check_deliverability=False, test_environment=True)
    except EmailNotValidError as exc:
        raise ValueError("Enter a valid email address.") from exc
    email = result.normalized.lower()
    if len(email) > 254:
        raise ValueError("Email is too long.")
    return email


Email = Annotated[str, AfterValidator(_normalize_email)]
FullName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120)]


class SignupIn(BaseModel):
    # "role" is never accepted: unknown fields are ignored and the server always assigns "clinician"
    model_config = ConfigDict(extra="ignore")

    full_name: FullName
    email: Email
    # generous pydantic bound; the password policy reports TOO_LONG with a proper code above 128
    password: Annotated[str, Field(max_length=1024)]


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    email: Email
    password: Annotated[str, Field(min_length=1, max_length=128)]


class ChangePasswordIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    current_password: Annotated[str, Field(min_length=1, max_length=128)]
    # generous pydantic bound; the policy reports TOO_LONG / TOO_SHORT with proper codes
    new_password: Annotated[str, Field(max_length=1024)]


class UserOut(BaseModel):
    id: UUID
    email: str
    full_name: str
    role: Literal["clinician"]
    last_login_at: datetime | None

    @classmethod
    def of(cls, user) -> UserOut:
        return cls(id=user.id, email=user.email, full_name=user.full_name, role=user.role,
                   last_login_at=user.last_login_at)


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["Bearer"] = "Bearer"
    expires_in: int
    user: UserOut
