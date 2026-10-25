"""GET /v1/me/outbound-mail."""

from datetime import datetime
from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.outbound_mail.schemas import (
    SentMailItemOut,
    SentMailPageOut,
)
from app.shared.actor import Actor

from fastapi import Depends, Query


async def list_sent_mail(
    container: Annotated[Container, Depends(get_container)],
    actor: Annotated[Actor, Depends(get_actor)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    before: datetime | None = None,
) -> SentMailPageOut:
    """The emails the caller sent from the platform, newest first."""
    page = await container.mail.list_sent_mail.execute(
        actor.user_id, limit=limit, before=before
    )
    return SentMailPageOut(
        items=[
            SentMailItemOut(
                id=item.id,
                to=list(item.to),
                subject=item.subject,
                snippet=item.snippet,
                sent_at=item.sent_at,
                status=item.status.value,
                attachment_name=item.attachment_name,
            )
            for item in page.items
        ],
        next_before=page.next_before,
    )
