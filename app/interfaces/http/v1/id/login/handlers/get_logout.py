"""GET /v1/id/logout?logout_challenge=: accept Hydra's logout request."""

from typing import Annotated

from app.interfaces.http.v1.id.dependencies import AuthDep
from app.interfaces.http.v1.id.login.schemas import RedirectToResponse

from fastapi import Query


async def get_logout(
    auth: AuthDep, logout_challenge: Annotated[str, Query(min_length=1)]
) -> RedirectToResponse:
    """Close our session and return where Hydra continues."""
    redirect = await auth.accept_logout.execute(logout_challenge)
    return RedirectToResponse(redirect_to=redirect)
