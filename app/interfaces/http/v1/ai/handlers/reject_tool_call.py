"""POST /v1/ai/chats/{id}/tool-calls/{call_id}/reject."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.ai.handlers.send_message import stream_turn
from app.interfaces.http.v1.ai.schemas import RejectToolCallBody, TurnResultResponse
from app.interfaces.http.v1.notebooks.handlers.sse import wants_stream
from app.modules.ai.application.tools.app_skills import app_for
from app.shared.actor import Actor
from app.shared.contracts.legal import APP_HEADER

from fastapi import Depends, Request
from fastapi.responses import StreamingResponse


async def reject_tool_call(
    chat_id: UUID,
    call_id: str,
    request: Request,
    container: Annotated[Container, Depends(get_container)],
    actor: Annotated[Actor, Depends(get_actor)],
    body: RejectToolCallBody | None = None,
) -> TurnResultResponse | StreamingResponse:
    """Reject a pending write; the reason goes back to the assistant."""
    app = app_for(request.headers.get(APP_HEADER), actor.client_id)
    if wants_stream(request):
        return await stream_turn(
            container.ai.reject_tool_call.stream(
                actor=actor,
                chat_id=chat_id,
                call_id=call_id,
                reason=body.reason if body else None,
                app=app,
            )
        )
    view = await container.ai.reject_tool_call.execute(
        actor=actor,
        chat_id=chat_id,
        call_id=call_id,
        reason=body.reason if body else None,
        app=app,
    )
    return TurnResultResponse.from_view(view)
