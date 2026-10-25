"""Use case: rename a chat."""

from collections.abc import Callable
from uuid import UUID

from app.modules.ai.application.chat_views import ChatViews
from app.modules.ai.application.owned_chat import ChatGuard
from app.modules.ai.application.views import ChatItemView
from app.modules.ai.ports.unit_of_work import AiUnitOfWork
from app.shared.actor import Actor


class RenameChat:
    """Changes the title of the caller's chat."""

    def __init__(
        self,
        *,
        uow_factory: Callable[[], AiUnitOfWork],
        guard: ChatGuard,
        views: ChatViews,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.guard = guard
        self.views = views

    async def execute(self, *, actor: Actor, chat_id: UUID, title: str) -> ChatItemView:
        """Save the new title (trimmed, non-empty)."""
        async with self.uow_factory() as uow:
            chat = await self.guard.chat(actor, await uow.chats.get_for_update(chat_id))
            chat.title = " ".join(title.split())
            await uow.chats.save(chat)
            await uow.commit()
        return self.views.chat_item(chat)
