"""Routes of the notebooks area: chat."""

from typing import Any

from app.interfaces.http.v1.notebooks.handlers import (
    delete_chat,
    get_chat,
    message_feedback,
    regenerate_chat,
    save_note,
    send_message,
)
from app.interfaces.http.v1.notebooks.handlers.sse import MEDIA_TYPE
from app.interfaces.http.v1.notebooks.schemas_chat import NotebookTurnResponse

from fastapi import APIRouter, status

router = APIRouter(prefix="/v1/notebooks", tags=["notebooks"])

# JSON by default; `Accept: text/event-stream` answers with server-sent events.
_STREAMABLE: dict[int | str, dict[str, Any]] = {
    status.HTTP_200_OK: {"content": {MEDIA_TYPE: {}}}
}

router.add_api_route("/{notebook_id}/chat", get_chat.get_chat, methods=["GET"])
router.add_api_route(
    "/{notebook_id}/chat/messages",
    send_message.send_message,
    methods=["POST"],
    response_model=NotebookTurnResponse,
    responses=_STREAMABLE,
)
router.add_api_route(
    "/{notebook_id}/chat/regenerate",
    regenerate_chat.regenerate_chat,
    methods=["POST"],
    response_model=NotebookTurnResponse,
    responses=_STREAMABLE,
)
router.add_api_route(
    "/{notebook_id}/chat",
    delete_chat.delete_chat,
    methods=["DELETE"],
    status_code=status.HTTP_204_NO_CONTENT,
)
router.add_api_route(
    "/{notebook_id}/chat/messages/{message_id}/feedback",
    message_feedback.message_feedback,
    methods=["POST"],
    status_code=status.HTTP_204_NO_CONTENT,
)
router.add_api_route(
    "/{notebook_id}/chat/messages/{message_id}/save-note",
    save_note.save_note,
    methods=["POST"],
    status_code=status.HTTP_201_CREATED,
)
