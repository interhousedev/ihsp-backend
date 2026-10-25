"""GET /v1/id/consent?consent_challenge=: consent screen data or a silent accept."""

from typing import Annotated

from app.interfaces.http.v1.id.dependencies import AuthDep
from app.interfaces.http.v1.id.login.schemas import ConsentInfoResponse

from fastapi import Query


async def get_consent(
    auth: AuthDep, consent_challenge: Annotated[str, Query(min_length=1)]
) -> ConsentInfoResponse:
    """First-party clients are accepted here; MCP clients get a screen."""
    info = await auth.get_consent_info.execute(consent_challenge)
    return ConsentInfoResponse.of(info)
