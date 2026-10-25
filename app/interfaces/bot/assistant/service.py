"""The web chat assistant as the bot uses it: one ongoing chat per user."""

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from app.interfaces.bot.assistant.store import AssistantStore
from app.modules.ai.application.turn_events import TurnEvent
from app.modules.ai.domain.assistant import ASSISTANT_ROLE, default_assistant
from app.modules.ai.domain.errors import ChatNotFoundError, WrongAssistantError
from app.shared.actor import Actor
from app.shared.contracts.files import FilesApi
from app.shared.usage_context import bind_usage_actor

Events = AsyncIterator[TurnEvent]

_CACHE: dict[int, "BotAssistant"] = {}


async def _primed(events: Events) -> Events:
    """Fetch the first event now, so a refusal raises here and not while streaming."""
    try:
        first = await anext(events)
    except StopAsyncIteration:
        first = None

    async def chained() -> Events:
        if first is not None:
            yield first
        async for event in events:
            yield event

    return chained()


class BotAssistant:
    """Sends messages and approval decisions to the AI module's use cases."""

    def __init__(self, ai: Any, files: FilesApi, store: AssistantStore) -> None:
        """`ai` is the AI module's `AiServices` (create, send, approve, reject)."""
        self.ai = ai
        self.files = files
        self.store = store

    async def chat_for(self, actor: Actor, *, fresh: bool = False) -> UUID:
        """The user's ongoing chat; a new one when there is none or `fresh`."""
        if not fresh:
            found = await self.store.chat_of(actor.user_id)
            if found is not None:
                return found
        item = await self.ai.create_chat.execute(
            actor=actor, assistant=default_assistant(actor)
        )
        chat_id: UUID = item.id
        await self.store.set_chat(actor.user_id, chat_id)
        return chat_id

    async def ask(
        self, actor: Actor, text: str, file_ids: list[UUID]
    ) -> tuple[UUID, Events]:
        """Start the turn; a deleted chat or a changed role starts a new chat."""
        # The model calls of this update are counted and access-checked for the user.
        bind_usage_actor(actor)

        def start(chat_id: UUID) -> Events:
            return self.ai.send_message.stream(  # type: ignore[no-any-return]
                actor=actor, chat_id=chat_id, text=text, file_ids=file_ids
            )

        chat_id = await self.chat_for(actor)
        try:
            return chat_id, await _primed(start(chat_id))
        except (ChatNotFoundError, WrongAssistantError):
            chat_id = await self.chat_for(actor, fresh=True)
            return chat_id, await _primed(start(chat_id))

    async def decide(
        self, actor: Actor, chat_id: UUID, call_id: str, *, approve: bool
    ) -> Events:
        """Approve (the tool runs) or reject a proposed write; the turn goes on."""
        bind_usage_actor(actor)
        if approve:
            events = self.ai.approve_tool_call.stream(
                actor=actor, chat_id=chat_id, call_id=call_id
            )
        else:
            events = self.ai.reject_tool_call.stream(
                actor=actor, chat_id=chat_id, call_id=call_id, reason=None
            )
        return await _primed(events)


def has_assistant_role(actor: Actor) -> bool:
    """Students and administrators have a general assistant (as on the web)."""
    return any(actor.has(role) for role in ASSISTANT_ROLE.values())


def bot_assistant(container: Any) -> BotAssistant | None:
    """The assistant of a container (None when the process built no AI module)."""
    ai = getattr(container, "ai", None)
    if ai is None:
        return None
    cached = _CACHE.get(id(container))
    if cached is not None and cached.ai is ai:
        return cached
    files: FilesApi = container.files.public
    built = BotAssistant(ai, files, AssistantStore(getattr(container, "redis", None)))
    _CACHE[id(container)] = built
    return built
