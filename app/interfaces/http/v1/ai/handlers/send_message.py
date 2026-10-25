"""POST /v1/ai/chats/{id}/messages."""

import json
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.ai.schemas import SendMessageBody, TurnResultResponse
from app.interfaces.http.v1.notebooks.handlers.sse import (
    HEADERS,
    MEDIA_TYPE,
    wants_stream,
)
from app.modules.ai.application.turn_events import TurnEvent
from app.shared.actor import Actor

from fastapi import Depends, Request
from fastapi.responses import StreamingResponse


async def send_message(
    chat_id: UUID,
    body: SendMessageBody,
    request: Request,
    container: Annotated[Container, Depends(get_container)],
    actor: Annotated[Actor, Depends(get_actor)],
) -> TurnResultResponse | StreamingResponse:
    """Send a message: one JSON result, or events with `Accept: text/event-stream`.

    The events are `status`, `step`, `delta` (the text being written),
    `round_end` (that text was a progress note), then `done` (the TurnResult:
    stored messages and usage) or `error`.
    """
    use_case = container.ai.send_message
    if wants_stream(request):
        events = use_case.stream(
            actor=actor,
            chat_id=chat_id,
            text=body.text,
            command=body.command,
            args=body.args,
            file_ids=body.file_ids,
            web_search=body.web_search,
        )
        return await stream_turn(events)
    view = await use_case.execute(
        actor=actor,
        chat_id=chat_id,
        text=body.text,
        command=body.command,
        args=body.args,
        file_ids=body.file_ids,
        web_search=body.web_search,
    )
    return TurnResultResponse.from_view(view)


async def stream_turn(events: AsyncIterator[TurnEvent]) -> StreamingResponse:
    """Answer 200 with the events once the first is known (a refusal raises)."""
    first = await anext(events)  # a refusal raises here, as problem+json
    return StreamingResponse(
        _blocks(first, events), media_type=MEDIA_TYPE, headers=HEADERS
    )


def frame(event: TurnEvent) -> bytes:
    """One SSE block; `done` carries the TurnResult."""
    data = event.data
    if event.result is not None:
        data = TurnResultResponse.from_view(event.result).model_dump(mode="json")
    body = json.dumps(data, ensure_ascii=False, default=str)
    return f"event: {event.name}\ndata: {body}\n\n".encode()


async def _blocks(
    first: TurnEvent, events: AsyncIterator[TurnEvent]
) -> AsyncIterator[bytes]:
    yield frame(first)
    async for event in events:
        yield frame(event)
