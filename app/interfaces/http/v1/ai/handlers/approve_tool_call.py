"""POST /v1/ai/chats/{id}/tool-calls/{call_id}/approve."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.ai.schemas import TurnResultResponse
from app.shared.actor import Actor

from fastapi import Depends


async def approve_tool_call(
    chat_id: UUID,
    call_id: str,
    container: Annotated[Container, Depends(get_container)],
    actor: Annotated[Actor, Depends(get_actor)],
) -> TurnResultResponse:
    """Approve a pending write; it runs once and the assistant continues."""
    view = await container.ai.approve_tool_call.execute(
        actor=actor, chat_id=chat_id, call_id=call_id
    )
    return TurnResultResponse.from_view(view)
