"""Use case: start a new chat with an assistant (AI-1)."""

from collections.abc import Callable

from app.modules.ai.application.assistant_profile import (
    profile_for,
    require_assistant_role,
)
from app.modules.ai.application.chat_views import ChatViews
from app.modules.ai.application.locale import LocaleResolver
from app.modules.ai.application.views import ChatItemView
from app.modules.ai.domain.assistant import Assistant
from app.modules.ai.domain.chat import Chat
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
        clock: Clock,
        settings: Settings,
        i18n: I18nCore,
        locale: LocaleResolver,
        views: ChatViews,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.settings = settings
        self.i18n = i18n
        self.locale = locale
        self.views = views

    async def execute(self, *, actor: Actor, assistant: Assistant) -> ChatItemView:
        """Create the chat; the title is replaced by the first message."""
        require_assistant_role(actor, assistant)
        locale = await self.locale.locale_of(actor.user_id)
        chat = Chat(
            id=new_id(),
            owner_id=actor.user_id,
            assistant=assistant,
            title=self.i18n.t(locale, "ai-chat-new"),
            model=profile_for(assistant, self.settings).model,
            last_message_at=self.clock.now(),
        )
        async with self.uow_factory() as uow:
            await uow.chats.add(chat)
            await uow.commit()
        return self.views.chat_item(chat)
