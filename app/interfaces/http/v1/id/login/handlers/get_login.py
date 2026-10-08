"""GET /v1/id/login?login_challenge=: login page data or a silent accept."""

from typing import Annotated

from app.interfaces.http.v1.id.dependencies import AuthDep
from app.interfaces.http.v1.id.login.schemas import LoginInfoResponse

from fastapi import Query


async def get_login(
    auth: AuthDep, login_challenge: Annotated[str, Query(min_length=1)]
) -> LoginInfoResponse:
    """Describe the login request (UF-ID-02)."""
    info = await auth.get_login_info.execute(login_challenge)
    return LoginInfoResponse.of(info)
