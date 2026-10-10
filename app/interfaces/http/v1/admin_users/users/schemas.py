"""Request bodies of the Administration user routes."""

from app.shared.actor import Role

from pydantic import BaseModel, EmailStr, Field


class BlockBody(BaseModel):
    """POST /v1/admin/users/{id}/block."""

    reason: str = Field(min_length=1, max_length=500)


class RolesBody(BaseModel):
    """POST /v1/admin/users/{id}/roles."""

    grant: list[Role] = []
    revoke: list[Role] = []


class ActivationUrlResponse(BaseModel):
    """The one-time link of a password reset."""

    activation_url: str


class SuspendBody(BaseModel):
    """POST /v1/admin/users/{id}/mail/suspend."""

    reason: str = Field(min_length=1, max_length=500)


class UserPatchBody(BaseModel):
    """PATCH /v1/admin/users/{id}: display name and email (omitted keeps)."""

    last_name: str | None = Field(default=None, min_length=1, max_length=255)
    first_name: str | None = Field(default=None, min_length=1, max_length=255)
    middle_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = None


class SetPasswordBody(BaseModel):
    """POST /v1/admin/users/{id}/set-password."""

    password: str = Field(min_length=1, max_length=1000)
    require_change: bool = Field(
        default=True,
        description="Ask the user to change it at the next login "
        "(when IHSP_FEATURES__CHANGE_PASSWORD_ON_LOGIN is on).",
    )
