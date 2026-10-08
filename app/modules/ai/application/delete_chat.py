"""Use case: delete a chat (soft; shares stop working through chat_for_share)."""

from collections.abc import Callable
from uuid import UUID

from app.modules.ai.domain.errors import ChatNotFoundError
from app.modules.ai.ports.unit_of_work import AiUnitOfWork
from app.shared.actor import Actor
from app.shared.clock import Clock


class DeleteChat:
    """Marks the caller's chat as deleted."""

    def __init__(
        self, *, uow_factory: Callable[[], AiUnitOfWork], clock: Clock
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def execute(self, *, actor: Actor, chat_id: UUID) -> None:
        """Soft-delete the chat and forget its pending approvals."""
        async with self.uow_factory() as uow:
            chat = await uow.chats.get_for_update(chat_id)
            if chat is None or chat.deleted_at or chat.owner_id != actor.user_id:
                raise ChatNotFoundError()
            chat.deleted_at = self.clock.now()
            chat.pending_approvals = 0
            await uow.chats.save(chat)
            await uow.commit()
