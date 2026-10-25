"""AiQueries: what other modules may ask the assistants (contract in § 3.6)."""

from collections.abc import Callable, Sequence
from typing import Any
from uuid import UUID

from app.modules.ai.application.chat_views import ChatViews
from app.modules.ai.application.locale import LocaleResolver
from app.modules.ai.application.pending_calls import expire_overdue
from app.modules.ai.domain.assistant import Assistant
from app.modules.ai.domain.chat import Chat, MessageRole
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
        """Return a chat for a share page; None for admin, author and deleted chats.

        Author chats talk about unpublished course drafts: they are never shared.
        """
        async with self.uow_factory() as uow:
            chat = await uow.chats.get(chat_id)
            if chat is None or chat.deleted_at or chat.assistant in _PRIVATE:
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

    async def chat_transcript(
        self, owner_id: UUID, chat_id: UUID, until_seq: int | None
    ) -> dict[str, Any] | None:
        """Return a chat as plain text for a notebook source.

        User and assistant texts only (tool calls, results and approval cards are
        not part of the text; empty texts are skipped). ``last_seq`` is the highest
        seq of the whole chat, so callers can tell when the snapshot is outdated.
        None for Administration chats, deleted chats and chats of another owner.
        """
        async with self.uow_factory() as uow:
            chat = await uow.chats.get(chat_id)
            if chat is None or not _readable_by(chat, owner_id):
                return None
            messages = await uow.messages.list_range(
                chat_id, after_seq=0, up_to_seq=until_seq
            )
            last_seq = await uow.messages.last_seq(chat_id)
        return {
            "title": chat.title,
            "last_message_at": chat.last_message_at,
            "last_seq": last_seq,
            "messages": [
                {"seq": m.seq, "role": m.role.value, "text": m.text}
                for m in messages
                if m.text.strip()
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

    async def message_for_share(self, chat_id: UUID, seq: int) -> dict[str, Any] | None:
        """Return one assistant answer of a shareable chat (text and owner only)."""
        async with self.uow_factory() as uow:
            chat = await uow.chats.get(chat_id)
            if chat is None or chat.deleted_at or chat.assistant in _PRIVATE:
                return None
            messages = await uow.messages.list_range(
                chat_id, after_seq=seq - 1, up_to_seq=seq
            )
        found = next((m for m in messages if m.seq == seq), None)
        if found is None or found.role is not MessageRole.ASSISTANT:
            return None
        return {"owner_id": chat.owner_id, "text": found.text}


_PRIVATE = (Assistant.ADMIN, Assistant.LMS_AUTHOR)


def _readable_by(chat: Chat, owner_id: UUID) -> bool:
    """Return True for a live student chat of this owner (no admin, no author)."""
    return (
        chat.owner_id == owner_id
        and chat.deleted_at is None
        and chat.assistant not in _PRIVATE
    )


def _notes(views: ChatViews, calls: list[Any], locale: str) -> list[str]:
    return [
        views.note(call.tool, locale)
        for call in calls
        if call.status is ToolStatus.DONE
    ]
