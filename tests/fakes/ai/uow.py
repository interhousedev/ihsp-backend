"""In-memory unit of work of the ai module (copies in and out, like a database)."""

import copy
from collections.abc import Callable
from datetime import datetime
from types import TracebackType
from typing import Self
from uuid import UUID

from app.modules.ai.domain.assistant import Assistant
from app.modules.ai.domain.chat import Chat, ChatMessage
from app.shared.notifications import AuditDraft


class FakeAiStore:
    """The "database": chats and messages shared by every unit of work."""

    def __init__(self) -> None:
        """Start empty."""
        self.chats: dict[UUID, Chat] = {}
        self.messages: dict[UUID, list[ChatMessage]] = {}
        self.audits: list[AuditDraft] = []
        self.commits = 0

    def chat_messages(self, chat_id: UUID) -> list[ChatMessage]:
        """Return copies of a chat's messages (for assertions)."""
        return copy.deepcopy(self.messages.get(chat_id, []))


class FakeChatRepository:
    """Chats of a FakeAiStore."""

    def __init__(self, store: FakeAiStore) -> None:
        """Bind to the store."""
        self.store = store

    async def add(self, chat: Chat) -> None:
        """Insert a chat."""
        self.store.chats[chat.id] = copy.deepcopy(chat)
        self.store.messages.setdefault(chat.id, [])

    async def get(self, chat_id: UUID) -> Chat | None:
        """Return a copy of the chat."""
        chat = self.store.chats.get(chat_id)
        return copy.deepcopy(chat) if chat else None

    async def get_for_update(self, chat_id: UUID) -> Chat | None:
        """Same as get (the fake has no row locks)."""
        return await self.get(chat_id)

    async def save(self, chat: Chat) -> None:
        """Store the chat's fields."""
        self.store.chats[chat.id] = copy.deepcopy(chat)

    async def list_for_owner(
        self,
        owner_id: UUID,
        assistant: Assistant,
        *,
        before: tuple[datetime, UUID] | None,
        limit: int,
    ) -> list[Chat]:
        """Newest first, live chats of the owner after the cursor."""
        rows = [
            c
            for c in self.store.chats.values()
            if c.owner_id == owner_id
            and c.assistant is assistant
            and c.deleted_at is None
        ]
        rows.sort(key=lambda c: (c.last_message_at, c.id), reverse=True)
        if before is not None:
            rows = [c for c in rows if (c.last_message_at, c.id) < before]
        return copy.deepcopy(rows[:limit])

    async def with_pending(self, owner_id: UUID) -> list[Chat]:
        """Live chats of the owner with approvals waiting."""
        rows = [
            c
            for c in self.store.chats.values()
            if c.owner_id == owner_id and not c.deleted_at and c.pending_approvals > 0
        ]
        return copy.deepcopy(rows)

    async def purge_admin_chats(self, last_message_before: datetime) -> int:
        """Delete old Administration chats."""
        old = [
            c.id
            for c in self.store.chats.values()
            if c.assistant is Assistant.ADMIN
            and c.last_message_at < last_message_before
        ]
        for chat_id in old:
            del self.store.chats[chat_id]
            self.store.messages.pop(chat_id, None)
        return len(old)


class FakeMessageRepository:
    """Messages of a FakeAiStore."""

    def __init__(self, store: FakeAiStore) -> None:
        """Bind to the store."""
        self.store = store

    def _rows(self, chat_id: UUID) -> list[ChatMessage]:
        return self.store.messages.setdefault(chat_id, [])

    async def add(self, message: ChatMessage) -> None:
        """Insert a message."""
        self._rows(message.chat_id).append(copy.deepcopy(message))

    async def save(self, message: ChatMessage) -> None:
        """Replace the stored message with the same seq."""
        rows = self._rows(message.chat_id)
        for index, row in enumerate(rows):
            if row.seq == message.seq:
                rows[index] = copy.deepcopy(message)

    async def last_seq(self, chat_id: UUID) -> int:
        """Highest seq, 0 when empty."""
        return max((m.seq for m in self._rows(chat_id)), default=0)

    async def get_for_update(self, chat_id: UUID, seq: int) -> ChatMessage | None:
        """Return a copy of one message."""
        for row in self._rows(chat_id):
            if row.seq == seq:
                return copy.deepcopy(row)
        return None

    async def list_tail(self, chat_id: UUID, limit: int) -> list[ChatMessage]:
        """Last `limit` messages, oldest first."""
        rows = sorted(self._rows(chat_id), key=lambda m: m.seq)
        return copy.deepcopy(rows[-limit:])

    async def list_range(
        self, chat_id: UUID, *, after_seq: int, up_to_seq: int | None
    ) -> list[ChatMessage]:
        """Messages with after_seq < seq <= up_to_seq."""
        rows = [
            m
            for m in sorted(self._rows(chat_id), key=lambda m: m.seq)
            if m.seq > after_seq and (up_to_seq is None or m.seq <= up_to_seq)
        ]
        return copy.deepcopy(rows)


class FakeAiUnitOfWork:
    """Unit of work over a FakeAiStore (writes apply at once; commit() only counts)."""

    def __init__(self, store: FakeAiStore) -> None:
        """Bind to the store."""
        self.store = store
        self.chats = FakeChatRepository(store)
        self.messages = FakeMessageRepository(store)
        self._audit: list[AuditDraft] = []

    async def __aenter__(self) -> Self:
        """Open the unit of work."""
        self._audit = []
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Nothing to roll back."""

    def audit(self, *drafts: AuditDraft) -> None:
        """Queue audit events."""
        self._audit.extend(drafts)

    async def commit(self) -> None:
        """Count the commit and publish audit events."""
        self.store.commits += 1
        self.store.audits.extend(self._audit)
        self._audit = []


def fake_uow_factory(store: FakeAiStore) -> Callable[[], FakeAiUnitOfWork]:
    """Return a factory that makes a fresh unit of work per use."""
    return lambda: FakeAiUnitOfWork(store)
