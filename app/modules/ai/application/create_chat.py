"""Use case: start a new chat with an assistant (AI-1)."""

from collections.abc import Callable
from uuid import UUID

from app.modules.ai.application.assistant_profile import effective_tier, profile_for
from app.modules.ai.application.chat_views import ChatViews
from app.modules.ai.application.locale import LocaleResolver
from app.modules.ai.application.owned_chat import ChatGuard
from app.modules.ai.application.views import ChatItemView
from app.modules.ai.domain.assistant import Assistant
from app.modules.ai.domain.chat import Chat, ChatTier
from app.modules.ai.ports.unit_of_work import AiUnitOfWork
from app.settings import Settings
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.i18n.core import I18nCore
from app.shared.ids import new_id


class CreateChat:
    """Creates an empty chat for the assistant the caller may use."""

    def __init__(
        self,
        *,
        uow_factory: Callable[[], AiUnitOfWork],
        guard: ChatGuard,
        clock: Clock,
        settings: Settings,
        i18n: I18nCore,
        locale: LocaleResolver,
        views: ChatViews,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.guard = guard
        self.clock = clock
        self.settings = settings
        self.i18n = i18n
        self.locale = locale
        self.views = views

    async def execute(
        self,
        *,
        actor: Actor,
        assistant: Assistant,
        tier: ChatTier | None = None,
        course_id: UUID | None = None,
    ) -> ChatItemView:
        """Create the chat; the title is replaced by the first message.

        The tier picks the student assistant's model class; the other assistants
        have one model and always store `fast`. The course author assistant needs
        `course_id` and the ``edit`` permission on that course; its chat is bound to
        the course and the course workspace for good.
        """
        scope = await self.guard.scope_for(actor, assistant, course_id)
        locale = await self.locale.locale_of(actor.user_id)
        chosen = effective_tier(assistant, tier)
        chat = Chat(
            id=new_id(),
            owner_id=actor.user_id,
            assistant=assistant,
            title=self.i18n.t(locale, "ai-chat-new"),
            model=profile_for(assistant, self.settings, chosen).model,
            last_message_at=self.clock.now(),
            tier=chosen,
            scope=scope,
        )
        async with self.uow_factory() as uow:
            await uow.chats.add(chat)
            await uow.commit()
        return self.views.chat_item(chat)
