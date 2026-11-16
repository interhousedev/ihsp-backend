"""Request bodies of the Administration user routes."""

from app.interfaces.http.v1.admin_users.schemas import AdminUserResponse
from app.shared.actor import Role
from app.shared.contracts.identity import AccountKind

from pydantic import BaseModel, EmailStr, Field


class BlockBody(BaseModel):
    """POST /v1/admin/users/{id}/block."""

    reason: str = Field(min_length=1, max_length=500)


class RolesBody(BaseModel):
    """POST /v1/admin/users/{id}/roles."""

    grant: list[Role] = []
    revoke: list[Role] = []


class UserCreateBody(BaseModel):
    """POST /v1/admin/users: a staff-like account without EMIS (no student/teacher)."""

    last_name: str = Field(min_length=1, max_length=255)
    first_name: str = Field(min_length=1, max_length=255)
    middle_name: str | None = Field(default=None, max_length=255)
    account_kind: AccountKind
    roles: list[Role] = Field(min_length=1)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=32)


class InvitedUserResponse(BaseModel):
    """The created account and its one-time Telegram invitation."""

    user: AdminUserResponse
    invite_url: str = Field(description="`https://t.me/<bot>?start=inv_<code>`")


class ActivationUrlResponse(BaseModel):
    """The one-time link of a password reset."""

    activation_url: str


class SuspendBody(BaseModel):
    """POST /v1/admin/users/{id}/mail/suspend."""

    reason: str = Field(min_length=1, max_length=500)


class UserPatchBody(BaseModel):
    """PATCH /v1/admin/users/{id}: names, login and email (omitted keeps)."""

    last_name: str | None = Field(default=None, min_length=1, max_length=255)
    first_name: str | None = Field(default=None, min_length=1, max_length=255)
    middle_name: str | None = Field(default=None, max_length=255)
    login: str | None = Field(default=None, max_length=100)
    email: EmailStr | None = None


class SetPasswordBody(BaseModel):
    """POST /v1/admin/users/{id}/set-password."""

    password: str = Field(min_length=1, max_length=1000)
    require_change: bool = Field(
        default=True,
        description="Ask the user to change it at the next login "
        "(when IHSP_FEATURES__CHANGE_PASSWORD_ON_LOGIN is on).",
    )


class UserPhotoResponse(BaseModel):
    """The profile photo of a user after it was set or removed."""

    photo_url: str | None = Field(
        description="Link to the photo, valid for an hour; null when there is none."
    )
