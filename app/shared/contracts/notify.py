"""Notify contracts (provider: notify module; consumers: bot and composition)."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from app.shared.contracts.identity import UserRef


class NotifyApi(Protocol):
    """Notification center for other modules."""

    async def unread_count(self, user_id: UUID) -> int:
        """Return the number of unread notifications."""
        ...

    async def latest_announcements(
        self, user_id: UUID, limit: int = 3
    ) -> list[dict[str, Any]]:
        """Return the newest announcements."""
        ...


class TelegramSender(Protocol):
    """Sends Telegram messages (aiogram Bot in production, a fake in tests).

    A button is {"text", "callback_data"}, {"text", "url"} or
    {"text", "web_app_url"}.
    """

    async def send_message(
        self,
        chat_id: int,
        text_html: str,
        buttons: list[list[dict[str, Any]]] | None = None,
    ) -> int:
        """Send a message and return its message id."""
        ...

    async def send_document(
        self,
        chat_id: int,
        filename: str,
        data: bytes,
        caption_html: str | None = None,
    ) -> int:
        """Send a document and return its message id."""
        ...

    async def delete_message(self, chat_id: int, message_id: int) -> None:
        """Delete a message."""
        ...


@dataclass(frozen=True, slots=True)
class RenderedMessage:
    """A Telegram message to send."""

    text_html: str
    buttons: list[list[dict[str, Any]]] | None = None
    documents: tuple[tuple[str, bytes], ...] = ()


@dataclass(frozen=True, slots=True)
class RenderContext:
    """Who a notification is rendered for."""

    user: UserRef
    locale: str
    telegram_user_id: int


Renderer = Callable[[dict[str, Any], RenderContext], Awaitable[RenderedMessage | None]]
