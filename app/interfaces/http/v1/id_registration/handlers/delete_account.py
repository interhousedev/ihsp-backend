"""DELETE /v1/id/me: delete the caller's account."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_client_ip, get_container
from app.interfaces.http.v1.id_registration.schemas import (
    DeleteAccountBody,
    DeleteAccountResponse,
)
from app.shared.actor import Actor

from fastapi import Depends, Request


async def delete_account(
    body: DeleteAccountBody,
    request: Request,
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
    ip: Annotated[str | None, Depends(get_client_ip)],
) -> DeleteAccountResponse:
    """Ask for the deletion; an administrator reviews it, then 30 days run (ID-29)."""
    ticket = await container.identity.emis.delete_account.execute(
        actor,
        password=body.password.get_secret_value(),
        otp_code=body.otp_code,
        ip=ip,
        user_agent=request.headers.get("user-agent"),
    )
    return DeleteAccountResponse(request_id=ticket.request_id, status=ticket.status)
