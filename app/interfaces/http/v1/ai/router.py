"""Routes of the AI assistants (`/v1/ai/*`)."""

from app.interfaces.http.v1.ai.handlers import (
    approve_tool_call,
    create_chat,
    delete_chat,
    get_chat,
    get_usage,
    list_chats,
    regenerate_answer,
    reject_tool_call,
    rename_chat,
    send_message,
    set_message_feedback,
)

from fastapi import APIRouter, status

router = APIRouter(prefix="/v1/ai", tags=["ai"])

router.add_api_route("/chats", list_chats.list_chats, methods=["GET"])
router.add_api_route("/chats", create_chat.create_chat, methods=["POST"])
router.add_api_route("/chats/{chat_id}", get_chat.get_chat, methods=["GET"])
router.add_api_route("/chats/{chat_id}", rename_chat.rename_chat, methods=["PATCH"])
router.add_api_route(
    "/chats/{chat_id}",
    delete_chat.delete_chat,
    methods=["DELETE"],
    status_code=status.HTTP_204_NO_CONTENT,
)
router.add_api_route(
    "/chats/{chat_id}/messages", send_message.send_message, methods=["POST"]
)
router.add_api_route(
    "/chats/{chat_id}/regenerate",
    regenerate_answer.regenerate_answer,
    methods=["POST"],
)
router.add_api_route(
    "/chats/{chat_id}/messages/{seq}/feedback",
    set_message_feedback.set_message_feedback,
    methods=["POST"],
    status_code=status.HTTP_204_NO_CONTENT,
)
router.add_api_route(
    "/chats/{chat_id}/tool-calls/{call_id}/approve",
    approve_tool_call.approve_tool_call,
    methods=["POST"],
)
router.add_api_route(
    "/chats/{chat_id}/tool-calls/{call_id}/reject",
    reject_tool_call.reject_tool_call,
    methods=["POST"],
)
router.add_api_route("/usage", get_usage.get_usage, methods=["GET"])
