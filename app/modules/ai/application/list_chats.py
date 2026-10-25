"""Use case: list the caller's chats of one assistant (newest first)."""

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from app.modules.ai.application.chat_views import ChatViews
from app.modules.ai.application.owned_chat import ChatGuard
from app.modules.ai.application.pending_calls import expire_overdue
from app.modules.ai.application.views import ChatItemView
from app.modules.ai.domain.assistant import Assistant
from app.modules.ai.ports.unit_of_work import AiUnitOfWork
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.pagination import Page, decode_cursor, encode_cursor


class ListChats:
    """Cursor-paginated chat list (cursor = last_message_at and id)."""

    def __init__(
        self,
        *,
        uow_factory: Callable[[], AiUnitOfWork],
        guard: ChatGuard,
        clock: Clock,
        views: ChatViews,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.guard = guard
        self.clock = clock
        self.views = views

    async def execute(
        self,
        *,
        actor: Actor,
        assistant: Assistant,
        cursor: str | None,
        limit: int,
        q: str | None = None,
        course_id: UUID | None = None,
    ) -> Page[ChatItemView]:
        """Return one page of the caller's live chats; `q` searches the titles.

        Author chats are listed per course: `course_id` is required for them and
        needs the ``edit`` permission; the other assistants ignore it.
        """
        await self.guard.assistant(actor, assistant, course_id)
        if assistant is not Assistant.LMS_AUTHOR:
            course_id = None
        needle = " ".join(q.split()) if q else None
        data = decode_cursor(cursor)
        before = (
            (datetime.fromisoformat(data["at"]), UUID(data["id"])) if data else None
        )
        async with self.uow_factory() as uow:
            rows = await uow.chats.list_for_owner(
                actor.user_id,
                assistant,
                before=before,
                limit=limit + 1,
                title_contains=needle or None,
                course_id=course_id,
            )
            page, more = rows[:limit], len(rows) > limit
            if any(chat.pending_approvals for chat in page):
                for chat in page:
                    await expire_overdue(uow, chat, self.clock.now())
                await uow.commit()
        next_cursor = None
        if more and page:
            last = page[-1]
            next_cursor = encode_cursor(
                {"at": last.last_message_at.isoformat(), "id": str(last.id)}
            )
        return Page(
            items=[self.views.chat_item(c) for c in page], next_cursor=next_cursor
        )
