"""Port: one transaction over the chat repositories."""

from collections.abc import Callable
from types import TracebackType
from typing import Protocol, Self

from app.modules.ai.ports.chat_repository import ChatRepository
from app.modules.ai.ports.message_repository import MessageRepository
from app.modules.ai.ports.web_pages import WebPageStore
from app.shared.notifications import AuditDraft


class AiUnitOfWork(Protocol):
    """Opens a transaction on entry; commit() writes audit events and commits."""

    @property
    def chats(self) -> ChatRepository:
        """Chats of the open transaction."""
        ...

    @property
    def messages(self) -> MessageRepository:
        """Messages of the open transaction."""
        ...

    @property
    def web_pages(self) -> WebPageStore:
        """Stored web pages and cached queries of the open transaction."""
        ...

    async def __aenter__(self) -> Self:
        """Open the transaction."""
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Roll back unless committed."""
        ...

    def audit(self, *drafts: AuditDraft) -> None:
        """Queue audit events for commit."""
        ...

    async def commit(self) -> None:
        """Commit the transaction."""
        ...


UowFactory = Callable[[], AiUnitOfWork]
