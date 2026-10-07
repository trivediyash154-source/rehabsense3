from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.db.models.user import Role
from app.schemas.types import UtcDatetime

# Roles a person may choose for themselves when signing up.
#
# ADMIN is deliberately absent: `authz.can_view_patient` grants an admin every
# patient record, so a self-selectable ADMIN would let anyone read all patient
# data simply by posting a role name. Administrators are provisioned
# separately. PHYSIOTHERAPIST is self-selectable because clinical access is
# gated on an ACTIVE PatientAssignment, not on the role alone -- a clinician
# with no assignments can see no one else's data.
SELF_ASSIGNABLE_ROLES = {Role.PATIENT, Role.PHYSIOTHERAPIST, Role.TECHNICIAN}


class UserCreate(BaseModel):
    email: EmailStr
    # Length is the property that actually resists guessing; a composition rule
    # ("one symbol") mostly pushes people toward predictable substitutions.
    password: str = Field(min_length=12, max_length=200)
    name: str = Field(min_length=2, max_length=120)
    phone: str | None = Field(default=None, max_length=32)
    role: Role = Role.PATIENT

    @field_validator("role")
    @classmethod
    def _no_self_elevation(cls, value: Role) -> Role:
        if value not in SELF_ASSIGNABLE_ROLES:
            raise ValueError(
                "This role cannot be chosen at signup. Ask an administrator to "
                "assign it."
            )
        return value


class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class UserPublic(BaseModel):
    """Never includes the password hash or the token version."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    name: str
    preferred_name: str | None = None
    phone: str | None = None
    role: Role
    timezone: str
    avatar_url: str | None = None
    preferences: dict = {}
    created_at: UtcDatetime


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    phone: str | None = Field(default=None, max_length=32)
    preferred_name: str | None = Field(default=None, max_length=120)
    timezone: str | None = Field(default=None, max_length=64)
    avatar_url: str | None = Field(default=None, max_length=512)
    preferences: dict | None = None


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserPublic


class RefreshRequest(BaseModel):
    refresh_token: str


class AuthResponse(BaseModel):
    """What a browser gets back from signup/login/me/refresh.

    Deliberately carries no token: the session lives in an HttpOnly cookie, so
    there is nothing here for an injected script to read.
    """

    user: UserPublic
    expires_in: int


class IdentityPublic(BaseModel):
    """One connected sign-in provider. Never a provider token or subject id."""

    provider: str
    email: str | None = None
    linked_at: UtcDatetime
    last_used_at: UtcDatetime | None = None


class SignInMethods(BaseModel):
    password: bool
    identities: list[IdentityPublic]
    # Providers this deployment can connect (configured on the server).
    available: dict[str, bool]


class AccountDeletion(BaseModel):
    # Typed by the person, so a stray click cannot delete an account.
    confirm: str = Field(max_length=20)
    # Required when the account has a password.
    password: str | None = Field(default=None, max_length=200)


class WsTicketRequest(BaseModel):
    session_id: int


class WsTicketResponse(BaseModel):
    ticket: str
    session_id: int
    expires_in: int
