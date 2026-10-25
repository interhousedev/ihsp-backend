"""POST /v1/id/reclaim/complete: set the new password, revoke everything."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_client_ip, get_container
from app.interfaces.http.v1.id_registration.schemas import CompleteReclaimBody

from fastapi import Depends, Request, Response, status


async def reclaim_complete(
    body: CompleteReclaimBody,
    request: Request,
    container: Annotated[Container, Depends(get_container)],
    ip: Annotated[str | None, Depends(get_client_ip)],
) -> Response:
    """Finish the reclaim (ID-28)."""
    await container.identity.emis.reclaim_complete.execute(
        reclaim_token=body.reclaim_token,
        new_password=body.new_password.get_secret_value(),
        email_code=body.email_code,
        ip=ip,
        user_agent=request.headers.get("user-agent"),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
