"""Use case: the user approves a pending write (AI-2, AI-3, AI-11).

Two short transactions around the tool run: the first claims the call under a row
lock (`pending_approval` -> `running`), so it can never run twice; the second
stores the result. No lock is held while the tool runs.
"""

from collections.abc import Callable
from uuid import UUID

from app.modules.ai.application.continue_turn import ContinueTurn
from app.modules.ai.application.decide_tool_call import (
    CallDecider,
    Claim,
    still_waiting,
    waiting_progress,
)
from app.modules.ai.application.locale import LocaleResolver
from app.modules.ai.application.pending_calls import refresh_counter
from app.modules.ai.application.tool_runner import ToolRunner
from app.modules.ai.application.tools.base import ToolContext
from app.modules.ai.application.turn_result import TurnResults
from app.modules.ai.application.views import TurnResultView
from app.modules.ai.domain.chat import Chat, ChatMessage
from app.modules.ai.domain.errors import ChatNotFoundError
from app.modules.ai.domain.tool_call import ToolCall, ToolStatus
from app.modules.ai.ports.turn_lock import TurnLock
from app.modules.ai.ports.unit_of_work import AiUnitOfWork
from app.shared.actor import Actor
from app.shared.notifications import AuditDraft


class ApproveToolCall:
    """Runs an approved write exactly once, then lets the assistant continue."""

    def __init__(
        self,
        *,
        uow_factory: Callable[[], AiUnitOfWork],
        decider: CallDecider,
        runner: ToolRunner,
        continue_turn: ContinueTurn,
        locks: TurnLock,
        locale: LocaleResolver,
        results: TurnResults,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.decider = decider
        self.runner = runner
        self.continue_turn = continue_turn
        self.locks = locks
        self.locale = locale
        self.results = results

    async def execute(
        self, *, actor: Actor, chat_id: UUID, call_id: str
    ) -> TurnResultView:
        """Approve the call, run it, store the result and continue the turn."""
        locale = await self.locale.locale_of(actor.user_id)
        async with self.locks.hold(chat_id):
            claim = await self._claim(actor, chat_id, call_id)
            ctx = ToolContext(actor, chat_id, locale, scope=claim.chat.scope)
            outcome = await self.runner.run_approved(
                claim.chat.assistant, ctx, claim.call
            )
            message, chat = await self._store(chat_id, claim.message.seq, outcome)
            if still_waiting(chat):
                progress = waiting_progress(chat, message)
            else:
                progress = await self.continue_turn.execute(
                    chat_id=chat_id, actor=actor, locale=locale, changed=[message]
                )
        return await self.results.build(actor, locale, progress)

    async def _claim(self, actor: Actor, chat_id: UUID, call_id: str) -> Claim:
        async with self.uow_factory() as uow:
            claim = await self.decider.claim(uow, actor, chat_id, call_id)
            self.decider.mark(claim, actor, ToolStatus.RUNNING)
            await uow.messages.save(claim.message)
            await refresh_counter(uow, claim.chat)
            uow.audit(
                AuditDraft(
                    type="ai.write_approved",
                    user_id=actor.user_id,
                    actor_id=actor.user_id,
                    metadata={
                        "chat_id": str(chat_id),
                        "call_id": call_id,
                        "tool": claim.call.tool,
                        "args": claim.call.args,
                    },
                )
            )
            await uow.commit()
        return claim

    async def _store(
        self, chat_id: UUID, seq: int, outcome: ToolCall
    ) -> tuple[ChatMessage, Chat]:
        async with self.uow_factory() as uow:
            message = await uow.messages.get_for_update(chat_id, seq)
            chat = await uow.chats.get(chat_id)
            if message is None or chat is None:
                raise ChatNotFoundError()
            for index, call in enumerate(message.tool_calls):
                if call.id == outcome.id:
                    message.tool_calls[index] = outcome
            await uow.messages.save(message)
            await uow.commit()
        return message, chat
