"""POST /v1/notebooks/{id}/chat/messages."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, Notebooks
from app.interfaces.http.v1.notebooks.handlers.sse import (
    stream_response,
    wants_stream,
)
from app.interfaces.http.v1.notebooks.schemas_chat import (
    NotebookTurnResponse,
    SendMessageBody,
)

from fastapi import Request
from fastapi.responses import StreamingResponse


async def send_message(
    notebook_id: UUID,
    body: SendMessageBody,
    request: Request,
    actor: MemberActor,
    notebooks: Notebooks,
) -> NotebookTurnResponse | StreamingResponse:
    """Answer a question: one JSON turn, or events with `Accept: text/event-stream`."""
    ask = notebooks.ask_notebook
    if wants_stream(request):
        events = ask.stream(
            actor, notebook_id, body.text, body.source_ids, body.anchor, body.web_search
        )
        return await stream_response(events)
    view = await ask.execute(
        actor, notebook_id, body.text, body.source_ids, body.anchor, body.web_search
    )
    return NotebookTurnResponse.from_view(view)
