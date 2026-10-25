"""A TelegramSender that records what it sends and can fail on demand."""

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SentItem:
    """One call to the sender."""

    kind: str  # "message", "document" or "delete"
    chat_id: int
    text_html: str | None = None
    buttons: list[list[dict[str, Any]]] | None = None
    filename: str | None = None
    data: bytes | None = None
    message_id: int = 0


class FakeTelegramSender:
    """Implements TelegramSender; `fail_next(chat_id, error)` raises once."""

    def __init__(self) -> None:
        """Start with an empty record."""
        self.items: list[SentItem] = []
        self._failures: dict[int, deque[Exception]] = defaultdict(deque)
        self._document_failures: dict[int, deque[Exception]] = defaultdict(deque)
        self._next_id = 100

    def fail_next(self, chat_id: int, error: Exception) -> None:
        """Make the next send to this chat raise the error (once)."""
        self._failures[chat_id].append(error)

    def fail_next_document(self, chat_id: int, error: Exception) -> None:
        """Make the next document sent to this chat raise the error (once)."""
        self._document_failures[chat_id].append(error)

    def messages(self, chat_id: int | None = None) -> list[SentItem]:
        """Return recorded text messages, optionally of one chat."""
        return [
            item
            for item in self.items
            if item.kind == "message" and chat_id in (None, item.chat_id)
        ]

    def documents(self, chat_id: int | None = None) -> list[SentItem]:
        """Return recorded documents, optionally of one chat."""
        return [
            item
            for item in self.items
            if item.kind == "document" and chat_id in (None, item.chat_id)
        ]

    @staticmethod
    def _raise_if_failing(failures: dict[int, deque[Exception]], chat_id: int) -> None:
        queue = failures.get(chat_id)
        if queue:
            raise queue.popleft()

    def _record(self, **fields: Any) -> int:
        self._next_id += 1
        self.items.append(SentItem(message_id=self._next_id, **fields))
        return self._next_id

    async def send_message(
        self,
        chat_id: int,
        text_html: str,
        buttons: list[list[dict[str, Any]]] | None = None,
    ) -> int:
        """Record a message."""
        self._raise_if_failing(self._failures, chat_id)
        return self._record(
            kind="message", chat_id=chat_id, text_html=text_html, buttons=buttons
        )

    async def send_document(
        self,
        chat_id: int,
        filename: str,
        data: bytes,
        caption_html: str | None = None,
    ) -> int:
        """Record a document."""
        self._raise_if_failing(self._document_failures, chat_id)
        return self._record(
            kind="document", chat_id=chat_id, filename=filename, data=data
        )

    async def delete_message(self, chat_id: int, message_id: int) -> None:
        """Record a deletion."""
        self._record(kind="delete", chat_id=chat_id)
