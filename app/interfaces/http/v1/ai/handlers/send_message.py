"""POST /v1/ai/chats/{id}/messages."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.ai.schemas import SendMessageBody, TurnResultResponse
from app.shared.actor import Actor

from fastapi import Depends


async def send_message(
    chat_id: UUID,
    body: SendMessageBody,
    container: Annotated[Container, Depends(get_container)],
    actor: Annotated[Actor, Depends(get_actor)],
) -> TurnResultResponse:
    """Send a message and return what the assistant did with it."""
    view = await container.ai.send_message.execute(
        actor=actor, chat_id=chat_id, text=body.text, file_ids=body.file_ids
    )
    return TurnResultResponse.from_view(view)
