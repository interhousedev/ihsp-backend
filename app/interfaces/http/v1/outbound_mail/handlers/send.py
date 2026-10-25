"""POST /v1/me/outbound-mail."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.outbound_mail.schemas import (
    SendOutboundRequest,
    SendOutboundResponse,
)
from app.shared.actor import Actor

from fastapi import Depends


async def send_outbound_mail(
    body: SendOutboundRequest,
    container: Annotated[Container, Depends(get_container)],
    actor: Annotated[Actor, Depends(get_actor)],
) -> SendOutboundResponse:
    """Send an email to anyone from the platform; one attachment from My files."""
    result = await container.mail.send_outbound.execute(
        actor.user_id,
        to=body.to,
        subject=body.subject,
        body=body.body,
        attachment_file_id=body.attachment_file_id,
    )
    return SendOutboundResponse(
        message_id=result.message_id,
        to=list(result.to),
        attachment_name=result.attachment_name,
    )
