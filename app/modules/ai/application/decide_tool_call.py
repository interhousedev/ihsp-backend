"""Shared steps of approving and rejecting a pending tool call (AI-3, AI-11)."""

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from app.modules.ai.application.continue_turn import TurnProgress
from app.modules.ai.application.pending_calls import find_call, refresh_counter
from app.modules.ai.application.views import TurnStatus
from app.modules.ai.domain.chat import Chat, ChatMessage
from app.modules.ai.domain.errors import (
    ChatNotFoundError,
    ToolCallExpiredError,
    ToolCallNotPendingError,
)
from app.modules.ai.domain.tool_call import ToolCall, ToolStatus
from app.modules.ai.ports.unit_of_work import AiUnitOfWork
from app.shared.actor import Actor
from app.shared.clock import Clock


@dataclass(slots=True)
class Claim:
    """A call that this request alone may now run or has just rejected."""

    chat: Chat
    message: ChatMessage
    call: ToolCall


class CallDecider:
    """Moves a call out of `pending_approval` exactly once."""

    def __init__(
        self, *, uow_factory: Callable[[], AiUnitOfWork], clock: Clock
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def claim(
        self,
        uow: AiUnitOfWork,
        actor: Actor,
        chat_id: UUID,
        call_id: str,
    ) -> Claim:
        """Lock the call; raise if it is not pending or has expired (and mark it).

        The caller sets the new status and commits.
        """
        chat = await uow.chats.get_for_update(chat_id)
        if chat is None or chat.deleted_at or chat.owner_id != actor.user_id:
            raise ChatNotFoundError()
        message, call = await find_call(uow, chat, call_id)
        if call.is_overdue(self.clock.now()):
            call.status = ToolStatus.EXPIRED
            await uow.messages.save(message)
            await refresh_counter(uow, chat)
            await uow.commit()
            raise ToolCallExpiredError(params={"call_id": call_id})
        if call.status is not ToolStatus.PENDING_APPROVAL:
            raise ToolCallNotPendingError(params={"call_id": call_id})
        return Claim(chat, message, call)

    def mark(self, claim: Claim, actor: Actor, status: ToolStatus) -> None:
        """Record who decided and when."""
        claim.call.status = status
        claim.call.decided_by = actor.user_id
        claim.call.decided_at = self.clock.now()


def still_waiting(chat: Chat) -> bool:
    """Return True if the chat has approvals left to decide."""
    return chat.pending_approvals > 0


def waiting_progress(chat: Chat, message: ChatMessage) -> TurnProgress:
    """Return the progress of a turn that has to wait for the other cards."""
    return TurnProgress(
        chat=chat, changed=[message], status=TurnStatus.AWAITING_APPROVAL
    )
