"""POST /v1/ai/chats/{id}/regenerate."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.ai.handlers.send_message import stream_turn
from app.interfaces.http.v1.ai.schemas import TurnResultResponse
from app.interfaces.http.v1.notebooks.handlers.sse import wants_stream
from app.shared.actor import Actor

from fastapi import Depends, Request
from fastapi.responses import StreamingResponse


async def regenerate_answer(
    chat_id: UUID,
    request: Request,
    container: Annotated[Container, Depends(get_container)],
    actor: Annotated[Actor, Depends(get_actor)],
) -> TurnResultResponse | StreamingResponse:
    """Answer the last user message again and return the new messages."""
    if wants_stream(request):
        return await stream_turn(
            container.ai.regenerate_answer.stream(actor=actor, chat_id=chat_id)
        )
    view = await container.ai.regenerate_answer.execute(actor=actor, chat_id=chat_id)
    return TurnResultResponse.from_view(view)
