"""Use case: thumbs up or down on an assistant message."""

from collections.abc import Callable
from uuid import UUID

from app.modules.ai.application.owned_chat import ChatGuard
from app.modules.ai.domain.chat import Feedback, MessageRole
from app.modules.ai.domain.errors import FeedbackNotAllowedError, MessageNotFoundError
from app.modules.ai.ports.unit_of_work import AiUnitOfWork
from app.shared.actor import Actor


class SetMessageFeedback:
    """Stores the rating (and an optional comment) on the caller's chat message."""

    def __init__(
        self, *, uow_factory: Callable[[], AiUnitOfWork], guard: ChatGuard
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.guard = guard

    async def execute(
        self,
        *,
        actor: Actor,
        chat_id: UUID,
        seq: int,
        rating: Feedback,
        comment: str | None,
    ) -> None:
        """Set or replace the rating; the same rating again changes nothing.

        The comment is personal text: it is stored on the message and never logged
        or audited.
        """
        text = (comment or "").strip() or None
        async with self.uow_factory() as uow:
            await self.guard.owned(uow, actor, chat_id)
            message = await uow.messages.get_for_update(chat_id, seq)
            if message is None:
                raise MessageNotFoundError(params={"seq": seq})
            if message.role is not MessageRole.ASSISTANT:
                raise FeedbackNotAllowedError(params={"seq": seq})
            if message.feedback is rating and text is None:
                return
            message.feedback = rating
            message.feedback_comment = text
            await uow.messages.set_feedback(message)
            await uow.commit()
