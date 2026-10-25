"""POST /v1/notebooks/{id}/chat/regenerate."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, Notebooks
from app.interfaces.http.v1.notebooks.handlers.sse import (
    stream_response,
    wants_stream,
)
from app.interfaces.http.v1.notebooks.schemas_chat import NotebookTurnResponse

from fastapi import Request
from fastapi.responses import StreamingResponse


async def regenerate_chat(
    notebook_id: UUID, request: Request, actor: MemberActor, notebooks: Notebooks
) -> NotebookTurnResponse | StreamingResponse:
    """Answer the last question again, as JSON or as events (see `send_message`)."""
    regenerate = notebooks.regenerate_chat
    if wants_stream(request):
        return await stream_response(regenerate.stream(actor, notebook_id))
    view = await regenerate.execute(actor, notebook_id)
    return NotebookTurnResponse.from_view(view)
