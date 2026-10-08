"""AiQueries: what other modules may ask the assistants (contract in § 3.6)."""

from collections.abc import Callable, Sequence
from typing import Any
from uuid import UUID

from app.modules.ai.application.chat_views import ChatViews
from app.modules.ai.application.locale import LocaleResolver
from app.modules.ai.application.pending_calls import expire_overdue
from app.modules.ai.domain.assistant import Assistant
from app.modules.ai.domain.chat import MessageRole
from app.modules.ai.domain.tool_call import ToolStatus
from app.modules.ai.ports.unit_of_work import AiUnitOfWork
from app.shared.clock import Clock


class AiQueriesImpl:
    """Implements `app.shared.contracts.ai.AiQueries`."""

    def __init__(
        self,
        *,
        uow_factory: Callable[[], AiUnitOfWork],
        clock: Clock,
        locale: LocaleResolver,
        views: ChatViews,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.locale = locale
        self.views = views

    async def pending_approvals(self, user_id: UUID) -> int:
        """Return how many approval cards of the user wait for a decision."""
        now = self.clock.now()
        async with self.uow_factory() as uow:
            chats = await uow.chats.with_pending(user_id)
            for chat in chats:
                await expire_overdue(uow, chat, now)
            await uow.commit()
        return sum(chat.pending_approvals for chat in chats)

    async def chat_for_share(
        self, chat_id: UUID, until_seq: int | None
    ) -> dict[str, Any] | None:
        """Return a chat for a share page; None for admin and deleted chats."""
        async with self.uow_factory() as uow:
            chat = await uow.chats.get(chat_id)
            if chat is None or chat.deleted_at or chat.assistant is Assistant.ADMIN:
                return None
            messages = await uow.messages.list_range(
                chat_id, after_seq=0, up_to_seq=until_seq
            )
        locale = await self.locale.locale_of(chat.owner_id)
        return {
            "title": chat.title,
            "owner_id": chat.owner_id,
            "messages": [
                {
                    "seq": m.seq,
                    "role": m.role.value,
                    "text": m.text,
                    "tool_notes": (
                        _notes(self.views, m.tool_calls, locale)
                        if m.role is MessageRole.ASSISTANT
                        else []
                    ),
                }
                for m in messages
            ],
        }

    async def chats_using_files(
        self, file_ids: Sequence[UUID]
    ) -> dict[UUID, list[tuple[UUID, str]]]:
        """Return (chat_id, title) per file for the chats whose messages use it."""
        async with self.uow_factory() as uow:
            found = await uow.messages.chats_using_files(list(file_ids))
        used: dict[UUID, list[tuple[UUID, str]]] = {}
        for file_id, chat_id, title in found:
            used.setdefault(file_id, []).append((chat_id, title))
        return used

    async def chat_owner(self, chat_id: UUID) -> UUID | None:
        """Return the owner of a live chat."""
        async with self.uow_factory() as uow:
            chat = await uow.chats.get(chat_id)
        if chat is None or chat.deleted_at:
            return None
        return chat.owner_id


def _notes(views: ChatViews, calls: list[Any], locale: str) -> list[str]:
    return [
        views.note(call.tool, locale)
        for call in calls
        if call.status is ToolStatus.DONE
    ]
