"""Schemas of the personal token endpoints."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from app.modules.identity.domain.personal_token import PersonalToken

from pydantic import BaseModel, Field

TokenScopeName = Literal["me:read", "me:write"]


class PersonalTokenResponse(BaseModel):
    """Personal token metadata (never the secret)."""

    id: UUID
    name: str
    prefix: str
    scopes: list[str]
    created_at: datetime
    expires_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None

    @classmethod
    def of(cls, token: PersonalToken) -> "PersonalTokenResponse":
        """Map a token."""
        return cls(
            id=token.id,
            name=token.name,
            prefix=token.prefix,
            scopes=list(token.scopes),
            created_at=token.created_at,
            expires_at=token.expires_at,
            last_used_at=token.last_used_at,
            revoked_at=token.revoked_at,
        )


class CreatePersonalTokenBody(BaseModel):
    """POST /v1/id/personal-tokens."""

    name: str = Field(min_length=1, max_length=80)
    scopes: list[TokenScopeName] = Field(min_length=1)
    expires_in_days: Literal[30, 90, 365]
    otp_code: str | None = None


class NewPersonalTokenResponse(BaseModel):
    """The new token; `token` is shown once."""

    personal_token: PersonalTokenResponse
    token: str
