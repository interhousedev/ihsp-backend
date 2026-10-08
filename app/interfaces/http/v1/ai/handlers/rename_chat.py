"""PATCH /v1/ai/chats/{id}."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.ai.schemas import ChatItemResponse, RenameChatBody
from app.shared.actor import Actor

from fastapi import Depends


async def rename_chat(
    chat_id: UUID,
    body: RenameChatBody,
    container: Annotated[Container, Depends(get_container)],
    actor: Annotated[Actor, Depends(get_actor)],
) -> ChatItemResponse:
    """Rename a chat of the caller."""
    view = await container.ai.rename_chat.execute(
        actor=actor, chat_id=chat_id, title=body.title
    )
    return ChatItemResponse.from_view(view)
