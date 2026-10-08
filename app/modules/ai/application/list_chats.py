"""Use case: list the caller's chats of one assistant (newest first)."""

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from app.modules.ai.application.assistant_profile import require_assistant_role
from app.modules.ai.application.chat_views import ChatViews
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
        clock: Clock,
        views: ChatViews,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.views = views

    async def execute(
        self, *, actor: Actor, assistant: Assistant, cursor: str | None, limit: int
    ) -> Page[ChatItemView]:
        """Return one page of the caller's live chats."""
        require_assistant_role(actor, assistant)
        data = decode_cursor(cursor)
        before = (
            (datetime.fromisoformat(data["at"]), UUID(data["id"])) if data else None
        )
        async with self.uow_factory() as uow:
            rows = await uow.chats.list_for_owner(
                actor.user_id, assistant, before=before, limit=limit + 1
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
