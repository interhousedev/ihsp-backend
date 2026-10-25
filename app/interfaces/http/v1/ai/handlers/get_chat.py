"""GET /v1/ai/chats/{id}."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.ai.schemas import ChatDetailResponse
from app.shared.actor import Actor

from fastapi import Depends


async def get_chat(
    chat_id: UUID,
    container: Annotated[Container, Depends(get_container)],
    actor: Annotated[Actor, Depends(get_actor)],
) -> ChatDetailResponse:
    """Return a chat of the caller with all its messages."""
    view = await container.ai.get_chat.execute(actor=actor, chat_id=chat_id)
    return ChatDetailResponse.from_detail(view)
