"""DELETE /v1/ai/chats/{id}."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.shared.actor import Actor

from fastapi import Depends, Response, status


async def delete_chat(
    chat_id: UUID,
    container: Annotated[Container, Depends(get_container)],
    actor: Annotated[Actor, Depends(get_actor)],
) -> Response:
    """Delete a chat of the caller."""
    await container.ai.delete_chat.execute(actor=actor, chat_id=chat_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
