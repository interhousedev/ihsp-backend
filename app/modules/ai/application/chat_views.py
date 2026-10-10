"""Builds localized views from chats and messages."""

from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.ai.application.views import (
    ChatItemView,
    ChatMessageView,
    DocumentCardView,
    PreviewFieldView,
    PreviewView,
    ToolCallView,
)
from app.modules.ai.domain.chat import Chat, ChatMessage
from app.modules.ai.domain.tool_call import PreviewData, ToolCall, ToolStatus
from app.modules.ai.domain.tools import note_key
from app.shared.i18n.core import I18nCore


class ChatViews:
    """Turns domain objects into views in a user's language."""

    def __init__(self, i18n: I18nCore) -> None:
        """Store the translations."""
        self.i18n = i18n

    def chat_item(self, chat: Chat) -> ChatItemView:
        """Return the list row of a chat."""
        return ChatItemView(
            id=chat.id,
            assistant=chat.assistant.value,
            title=chat.title,
            last_message_at=chat.last_message_at,
            pending_approvals=chat.pending_approvals,
            tier=chat.tier.value,
            course_id=chat.course_id,
        )

    def note(self, tool: str, locale: str) -> str:
        """Return the "Looked up…" sentence of a tool."""
        return self.i18n.t(locale, note_key(tool))

    def _preview(self, data: PreviewData | None, locale: str) -> PreviewView | None:
        if data is None:
            return None
        return PreviewView(
            title=self.i18n.t(locale, data.title_key, **data.title_params),
            fields=[
                PreviewFieldView(
                    label=self.i18n.t(locale, f.label_key),
                    value=f.value,
                    sensitive=f.sensitive,
                )
                for f in data.fields
            ],
            items=list(data.items),
        )

    def tool_call(self, call: ToolCall, locale: str, now: datetime) -> ToolCallView:
        """Return a tool call; an overdue pending one is shown as expired."""
        status = ToolStatus.EXPIRED if call.is_overdue(now) else call.status
        return ToolCallView(
            id=call.id,
            tool=call.tool,
            access=call.access.value,
            status=status.value,
            note=self.note(call.tool, locale),
            preview=self._preview(call.preview, locale),
            reject_reason=call.reject_reason,
            expires_at=call.expires_at,
            document=self._document(call),
        )

    @staticmethod
    def _document(call: ToolCall) -> DocumentCardView | None:
        """The file card of a finished ``make_document`` call."""
        result: dict[str, Any] | None = call.result
        if call.tool != "make_document" or call.status is not ToolStatus.DONE:
            return None
        if not result or result.get("kind") not in ("docx", "xlsx", "pptx"):
            return None
        return DocumentCardView(
            file_id=UUID(str(result["file_id"])),
            name=str(result["name"]),
            kind=result["kind"],
            size=int(result.get("size") or 0),
        )

    def message(
        self, message: ChatMessage, locale: str, now: datetime
    ) -> ChatMessageView:
        """Return a message with its tool calls."""
        return ChatMessageView(
            seq=message.seq,
            role=message.role.value,
            text=message.text,
            file_ids=list(message.file_ids),
            tool_calls=[self.tool_call(c, locale, now) for c in message.tool_calls],
            created_at=message.created_at,
            feedback=message.feedback.value if message.feedback else None,
            web=list(message.content.web),
        )
