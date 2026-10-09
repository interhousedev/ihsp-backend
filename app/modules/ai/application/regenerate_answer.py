"""Use case: answer the last user message again (AI-2, AI-8)."""

from collections.abc import Callable
from uuid import UUID

from app.modules.ai.application.assistant_profile import profile_for
from app.modules.ai.application.continue_turn import TAIL_MESSAGES, ContinueTurn
from app.modules.ai.application.locale import LocaleResolver
from app.modules.ai.application.owned_chat import ChatGuard
from app.modules.ai.application.pending_calls import expire_overdue, refresh_counter
from app.modules.ai.application.turn_result import TurnResults
from app.modules.ai.application.views import TurnResultView
from app.modules.ai.domain.chat import Chat, last_turn
from app.modules.ai.domain.errors import (
    AiLimitReachedError,
    ApprovalPendingError,
    ChatNotFoundError,
    NothingToRegenerateError,
)
from app.modules.ai.ports.turn_lock import TurnLock
from app.modules.ai.ports.unit_of_work import AiUnitOfWork
from app.settings import Settings
from app.shared.actor import Actor
from app.shared.clock import Clock


class RegenerateAnswer:
    """Removes the last answer and runs the same turn again."""

    def __init__(
        self,
        *,
        uow_factory: Callable[[], AiUnitOfWork],
        guard: ChatGuard,
        continue_turn: ContinueTurn,
        locks: TurnLock,
        locale: LocaleResolver,
        results: TurnResults,
        clock: Clock,
        settings: Settings,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.guard = guard
        self.continue_turn = continue_turn
        self.locks = locks
        self.locale = locale
        self.results = results
        self.clock = clock
        self.settings = settings

    async def execute(self, *, actor: Actor, chat_id: UUID) -> TurnResultView:
        """Check the budget, drop the messages after the last user message, rerun."""
        locale = await self.locale.locale_of(actor.user_id)
        async with self.locks.hold(chat_id):
            async with self.uow_factory() as uow:
                chat = await self.guard.owned(uow, actor, chat_id)
            await self.guard.admit_message(actor, chat)
            await self._require_budget(chat, locale)
            await self._drop_last_answer(chat_id)
            progress = await self.continue_turn.execute(
                chat_id=chat_id, actor=actor, locale=locale
            )
        return await self.results.build(actor.user_id, locale, progress)

    async def _require_budget(self, chat: Chat, locale: str) -> None:
        """Refuse a rerun the user cannot afford, before anything is removed."""
        hit = await self.continue_turn.precheck_replay(chat, locale)
        if hit is not None:
            raise AiLimitReachedError(params=hit.params())

    async def _drop_last_answer(self, chat_id: UUID) -> None:
        """Delete what the assistant added after the last user message."""
        async with self.uow_factory() as uow:
            chat = await uow.chats.get_for_update(chat_id)
            if chat is None:
                raise ChatNotFoundError()
            await expire_overdue(uow, chat, self.clock.now())
            turn = last_turn(await uow.messages.list_tail(chat_id, TAIL_MESSAGES))
            if turn is None:
                raise NothingToRegenerateError()
            user, answer = turn
            if any(message.pending_calls() for message in answer):
                raise ApprovalPendingError()
            await uow.messages.delete_after(chat_id, user.seq)
            chat.model = profile_for(chat.assistant, self.settings, chat.tier).model
            await refresh_counter(uow, chat)
            await uow.commit()
