"""Schemas of the OAuth client routes."""

from datetime import datetime

from app.modules.identity.application.list_oauth_clients import OAuthClientView

from pydantic import BaseModel


class OAuthClientResponse(BaseModel):
    """{client_id, name, verified, dynamic, last_used_at}."""

    client_id: str
    name: str
    verified: bool
    dynamic: bool
    last_used_at: datetime | None

    @classmethod
    def of(cls, view: OAuthClientView) -> "OAuthClientResponse":
        """Map a client view."""
        return cls(
            client_id=view.client_id,
            name=view.name,
            verified=view.verified,
            dynamic=view.dynamic,
            last_used_at=view.last_used_at,
        )


class VerifyBody(BaseModel):
    """POST /v1/admin/oauth-clients/{client_id}/verify."""

    verified: bool
