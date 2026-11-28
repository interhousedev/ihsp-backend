"""Notify contracts (provider: notify module; consumers: bot and composition)."""

from collections.abc import Awaitable, Callable, Collection, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from app.shared.contracts.identity import UserRef
from app.shared.notifications import NotificationType


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

    async def delete_for_user(
        self, user_id: UUID, types: Collection[NotificationType]
    ) -> int:
        """Delete the user's notifications of the given types; return how many."""
        ...


class KnowledgeGapNotifier(Protocol):
    """Tells every administrator that an AI chat found nothing in the knowledge base."""

    async def notify_knowledge_gap(
        self,
        *,
        query: str,
        chat_kind: str,
        user_role: str,
        audience: str,
        chat_id: str | None = None,
        notebook_id: str | None = None,
    ) -> int:
        """Notify all administrators; return how many notifications were queued.

        `audience` is "guest", "student" or "staff": who asked the question.

        The same normalized query (lowercase, collapsed whitespace) is not
        announced again within 24 hours; then 0 is returned.
        """
        ...


class ChatAnswerNotifier(Protocol):
    """Tells a user that the assistant answered while they were away."""

    async def notify_chat_answer_ready(
        self, *, user_id: UUID, chat_id: UUID, seq: int, prompt: str
    ) -> None:
        """Queue one notice per answer (`seq` of the answer in the chat).

        The notice names the question and links to the chat; it never carries the
        answer. Telegram delivery follows the user's link and preferences.
        """
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

    async def send_photo(
        self,
        chat_id: int,
        photo: "PhotoRef",
        caption_html: str | None = None,
        buttons: list[list[dict[str, Any]]] | None = None,
    ) -> "SentPhoto":
        """Send one photo (a cached ``file_id`` may replace the upload)."""
        ...

    async def send_media_group(
        self, chat_id: int, photos: "Sequence[PhotoRef]"
    ) -> "list[SentPhoto]":
        """Send 2 to 10 photos as one album (no caption, no buttons)."""
        ...

    async def delete_message(self, chat_id: int, message_id: int) -> None:
        """Delete a message."""
        ...


@dataclass(frozen=True, slots=True)
class BotRoute:
    """The sender of one registered bot."""

    sender: TelegramSender
    is_default: bool


@runtime_checkable
class BotSenders(Protocol):
    """A TelegramSender (the default bot) that also knows the other bots."""

    async def route(self, bot_id: str | None, *, personal: bool) -> BotRoute | None:
        """The bot to send through; None when that bot may not send it.

        `bot_id` None means the default bot. `personal` is a personal
        notification (switch `notifications`), otherwise an announcement.
        """
        ...


@dataclass(frozen=True, slots=True)
class PhotoRef:
    """A photo to send; ``cache_key`` names the content for Telegram file_id reuse."""

    name: str
    data: bytes
    cache_key: str


@dataclass(frozen=True, slots=True)
class SentPhoto:
    """Result of sending a photo: the message and the file_id Telegram assigned."""

    message_id: int
    file_id: str


@dataclass(frozen=True, slots=True)
class RenderedMessage:
    """A Telegram message to send."""

    text_html: str
    buttons: list[list[dict[str, Any]]] | None = None
    documents: tuple[tuple[str, bytes], ...] = ()
    photos: tuple[PhotoRef, ...] = ()


@dataclass(frozen=True, slots=True)
class RenderContext:
    """Who a notification is rendered for."""

    user: UserRef
    locale: str
    telegram_user_id: int


Renderer = Callable[[dict[str, Any], RenderContext], Awaitable[RenderedMessage | None]]
