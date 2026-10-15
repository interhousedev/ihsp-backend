"""POST /v1/id/register/complete: create the account."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_client_ip, get_container
from app.interfaces.http.v1.id_registration.schemas import (
    CompleteRegistrationBody,
    CompleteRegistrationResponse,
)

from fastapi import Depends, Request


async def register_complete(
    body: CompleteRegistrationBody,
    request: Request,
    container: Annotated[Container, Depends(get_container)],
    ip: Annotated[str | None, Depends(get_client_ip)],
) -> CompleteRegistrationResponse:
    """Set the password, confirm the email, create the account (ID-4, ID-5)."""
    registered = await container.identity.emis.register_complete.execute(
        registration_token=body.registration_token,
        password=body.password.get_secret_value(),
        email_code=body.email_code,
        confirm_import_match=body.confirm_import_match,
        login_challenge=body.login_challenge,
        ip=ip,
        user_agent=request.headers.get("user-agent"),
    )
    return CompleteRegistrationResponse(
        login=registered.login,
        redirect_to=registered.redirect_to,
        login_ticket=registered.login_ticket,
    )
