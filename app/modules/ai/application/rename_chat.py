"""Use case: rename a chat."""

from collections.abc import Callable
from uuid import UUID

from app.modules.ai.application.chat_views import ChatViews
from app.modules.ai.application.views import ChatItemView
from app.modules.ai.domain.errors import ChatNotFoundError
from app.modules.ai.ports.unit_of_work import AiUnitOfWork
from app.shared.actor import Actor


class RenameChat:
    """Changes the title of the caller's chat."""

    def __init__(
        self, *, uow_factory: Callable[[], AiUnitOfWork], views: ChatViews
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.views = views

    async def execute(self, *, actor: Actor, chat_id: UUID, title: str) -> ChatItemView:
        """Save the new title (trimmed, non-empty)."""
        async with self.uow_factory() as uow:
            chat = await uow.chats.get_for_update(chat_id)
            if chat is None or chat.deleted_at or chat.owner_id != actor.user_id:
                raise ChatNotFoundError()
            chat.title = " ".join(title.split())
            await uow.chats.save(chat)
            await uow.commit()
        return self.views.chat_item(chat)
