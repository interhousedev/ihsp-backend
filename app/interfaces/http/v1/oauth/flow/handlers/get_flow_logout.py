"""GET /v1/oauth/flow/logout?logout_challenge=: Hydra's ``urls.logout``."""

from typing import Annotated

from app.interfaces.http.v1.id.dependencies import AuthDep
from app.interfaces.http.v1.oauth.flow.redirect import hydra_redirect

from fastapi import Query
from fastapi.responses import RedirectResponse


async def get_flow_logout(
    auth: AuthDep, logout_challenge: Annotated[str, Query(min_length=1)]
) -> RedirectResponse:
    """Accept the logout and continue with Hydra's end-session step."""
    return hydra_redirect(await auth.route_logout_request.execute(logout_challenge))
