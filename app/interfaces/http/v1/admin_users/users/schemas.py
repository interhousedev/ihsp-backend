"""Request bodies of the Administration user routes."""

from app.shared.actor import Role

from pydantic import BaseModel, Field


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
