"""Use case: open a chat with all its messages."""

from collections.abc import Callable
from uuid import UUID

from app.modules.ai.application.chat_views import ChatViews
from app.modules.ai.application.late_bindings import LateBindings
from app.modules.ai.application.locale import LocaleResolver
from app.modules.ai.application.owned_chat import ChatGuard
from app.modules.ai.application.pending_calls import expire_overdue
from app.modules.ai.application.views import ChatDetailView
from app.modules.ai.ports.unit_of_work import AiUnitOfWork
from app.shared.actor import Actor
from app.shared.clock import Clock


class GetChat:
    """Returns a chat of the caller; overdue approvals are expired on the way."""

    def __init__(
        self,
        *,
        uow_factory: Callable[[], AiUnitOfWork],
        guard: ChatGuard,
        clock: Clock,
        locale: LocaleResolver,
        views: ChatViews,
        bindings: LateBindings,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.guard = guard
        self.clock = clock
        self.locale = locale
        self.views = views
        self.bindings = bindings

    async def execute(self, *, actor: Actor, chat_id: UUID) -> ChatDetailView:
        """Return the chat or raise ChatNotFoundError (also for other people's)."""
        now = self.clock.now()
        async with self.uow_factory() as uow:
            chat = await self.guard.owned(uow, actor, chat_id)
            if await expire_overdue(uow, chat, now):
                await uow.commit()
            messages = await uow.messages.list_range(
                chat_id, after_seq=0, up_to_seq=None
            )
        locale = await self.locale.locale_of(actor.user_id)
        lookup = self.bindings.share_lookup
        shared = await lookup.is_shared(chat_id) if lookup is not None else False
        return ChatDetailView(
            chat=self.views.chat_item(chat),
            messages=[self.views.message(m, locale, now) for m in messages],
            shared=shared,
        )
