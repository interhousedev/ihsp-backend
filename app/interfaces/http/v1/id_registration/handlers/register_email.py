"""POST /v1/id/register/email: mail a confirmation code."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container
from app.interfaces.http.v1.id_registration.schemas import SendRegistrationEmailBody

from fastapi import Depends, Response, status


async def register_email(
    body: SendRegistrationEmailBody,
    container: Annotated[Container, Depends(get_container)],
) -> Response:
    """Send the code to the recovery email (ID-4)."""
    await container.identity.emis.register_email_code.execute(
        registration_token=body.registration_token, email=body.email
    )
    return Response(status_code=status.HTTP_202_ACCEPTED)
