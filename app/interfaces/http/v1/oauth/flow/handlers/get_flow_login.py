"""GET /v1/oauth/flow/login?login_challenge=: Hydra's ``urls.login``."""

from typing import Annotated

from app.interfaces.http.v1.id.dependencies import AuthDep
from app.interfaces.http.v1.oauth.flow.redirect import hydra_redirect

from fastapi import Query
from fastapi.responses import RedirectResponse


async def get_flow_login(
    auth: AuthDep, login_challenge: Annotated[str, Query(min_length=1)]
) -> RedirectResponse:
    """Continue with Hydra when the session allows (SSO), else open the login form."""
    return hydra_redirect(await auth.route_login_request.execute(login_challenge))
