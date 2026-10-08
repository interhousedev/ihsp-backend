"""GET /v1/oauth/flow/consent?consent_challenge=: Hydra's ``urls.consent``."""

from typing import Annotated

from app.interfaces.http.v1.id.dependencies import AuthDep
from app.interfaces.http.v1.oauth.flow.redirect import hydra_redirect

from fastapi import Query
from fastapi.responses import RedirectResponse


async def get_flow_consent(
    auth: AuthDep, consent_challenge: Annotated[str, Query(min_length=1)]
) -> RedirectResponse:
    """Accept our own apps at once; MCP clients get the consent page."""
    return hydra_redirect(await auth.route_consent_request.execute(consent_challenge))
