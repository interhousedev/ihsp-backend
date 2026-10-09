"""POST /v1/ai/chats/{id}/regenerate."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.ai.schemas import TurnResultResponse
from app.shared.actor import Actor

from fastapi import Depends


async def regenerate_answer(
    chat_id: UUID,
    container: Annotated[Container, Depends(get_container)],
    actor: Annotated[Actor, Depends(get_actor)],
) -> TurnResultResponse:
    """Answer the last user message again and return the new messages."""
    view = await container.ai.regenerate_answer.execute(actor=actor, chat_id=chat_id)
    return TurnResultResponse.from_view(view)
