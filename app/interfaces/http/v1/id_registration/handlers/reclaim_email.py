"""POST /v1/id/reclaim/email: mail a confirmation code to the new email."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container
from app.interfaces.http.v1.id_registration.schemas import SendReclaimEmailBody

from fastapi import Depends, Response, status


async def reclaim_email(
    body: SendReclaimEmailBody,
    container: Annotated[Container, Depends(get_container)],
) -> Response:
    """Send the code to the new recovery email."""
    await container.identity.emis.reclaim_email_code.execute(
        reclaim_token=body.reclaim_token, email=body.email
    )
    return Response(status_code=status.HTTP_202_ACCEPTED)
