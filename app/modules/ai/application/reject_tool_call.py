"""Use case: the user rejects a pending write, optionally with a reason (AI-3)."""

from collections.abc import Callable
from uuid import UUID

from app.modules.ai.application.continue_turn import ContinueTurn
from app.modules.ai.application.decide_tool_call import (
    CallDecider,
    still_waiting,
    waiting_progress,
)
from app.modules.ai.application.locale import LocaleResolver
from app.modules.ai.application.pending_calls import refresh_counter
from app.modules.ai.application.turn_result import TurnResults
from app.modules.ai.application.views import TurnResultView
from app.modules.ai.domain.tool_call import ToolStatus
from app.modules.ai.ports.turn_lock import TurnLock
from app.modules.ai.ports.unit_of_work import AiUnitOfWork
from app.shared.actor import Actor

REASON_MAX_CHARS = 500


class RejectToolCall:
    """Rejects a call; the reason goes back to the model."""

    def __init__(
        self,
        *,
        uow_factory: Callable[[], AiUnitOfWork],
        decider: CallDecider,
        continue_turn: ContinueTurn,
        locks: TurnLock,
        locale: LocaleResolver,
        results: TurnResults,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.decider = decider
        self.continue_turn = continue_turn
        self.locks = locks
        self.locale = locale
        self.results = results

    async def execute(
        self, *, actor: Actor, chat_id: UUID, call_id: str, reason: str | None
    ) -> TurnResultView:
        """Reject the call and let the assistant answer."""
        locale = await self.locale.locale_of(actor.user_id)
        clean = (reason or "").strip()[:REASON_MAX_CHARS] or None
        async with self.locks.hold(chat_id):
            async with self.uow_factory() as uow:
                claim = await self.decider.claim(uow, actor, chat_id, call_id)
                self.decider.mark(claim, actor, ToolStatus.REJECTED)
                claim.call.reject_reason = clean
                await uow.messages.save(claim.message)
                await refresh_counter(uow, claim.chat)
                await uow.commit()
            if still_waiting(claim.chat):
                progress = waiting_progress(claim.chat, claim.message)
            else:
                progress = await self.continue_turn.execute(
                    chat_id=chat_id,
                    actor=actor,
                    locale=locale,
                    changed=[claim.message],
                )
        return await self.results.build(actor.user_id, locale, progress)
