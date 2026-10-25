"""Schemas of the token handler endpoints."""

from typing import Literal

from app.modules.identity.application.token_grant import TokenGrant

from pydantic import BaseModel, Field


class TokenResponse(BaseModel):
    """TokenResponse: the refresh token only ever travels in the cookie."""

    access_token: str
    token_type: Literal["Bearer"] = "Bearer"
    expires_in: int

    @classmethod
    def of(cls, grant: TokenGrant) -> "TokenResponse":
        """Map a grant."""
        return cls(access_token=grant.access_token, expires_in=grant.expires_in)


class TokenBody(BaseModel):
    """POST /v1/oauth/token."""

    client_id: str = Field(min_length=1, max_length=64)
    code: str = Field(min_length=1)
    code_verifier: str = Field(min_length=1)
    redirect_uri: str = Field(min_length=1)


class ClientBody(BaseModel):
    """POST /v1/oauth/refresh and /v1/oauth/logout."""

    client_id: str = Field(min_length=1, max_length=64)


class LogoutResponse(BaseModel):
    """Hydra's end-session URL."""

    logout_url: str


class TelegramTokenBody(BaseModel):
    """POST /v1/oauth/telegram."""

    client_id: Literal["sp", "staff"]
    init_data: str = Field(min_length=1)
