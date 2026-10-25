"""POST /v1/ai/chats."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.ai.schemas import ChatItemResponse, CreateChatBody
from app.modules.ai.domain.assistant import Assistant
from app.modules.ai.domain.chat import ChatTier
from app.shared.actor import Actor

from fastapi import Depends


async def create_chat(
    body: CreateChatBody,
    container: Annotated[Container, Depends(get_container)],
    actor: Annotated[Actor, Depends(get_actor)],
) -> ChatItemResponse:
    """Start a chat with the student, Administration or course author assistant."""
    view = await container.ai.create_chat.execute(
        actor=actor,
        assistant=Assistant(body.assistant),
        tier=ChatTier(body.tier) if body.tier else None,
        course_id=body.course_id,
    )
    return ChatItemResponse.from_view(view)
