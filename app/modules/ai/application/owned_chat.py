"""The rule that a chat route works on the caller's own live chat.

For the course author assistant the caller must also still hold ``edit`` on the
chat's course: the LMS is asked on every call, so a staff member who is removed
from the course loses the assistant at once.
"""

from uuid import UUID

from app.modules.ai.application.assistant_profile import require_assistant_role
from app.modules.ai.domain.assistant import Assistant
from app.modules.ai.domain.chat import Chat
from app.modules.ai.domain.chat_scope import ChatScope
from app.modules.ai.domain.errors import ChatNotFoundError, CourseRequiredError
from app.modules.ai.ports.author_gate import AuthorGate
from app.modules.ai.ports.unit_of_work import AiUnitOfWork
from app.settings import Settings
from app.shared.actor import Actor
from app.shared.rate_limit import RateLimiter

RATE_WINDOW_SECONDS = 60
COURSE_CHAT_RATE_KEY = "lms-chat:{user_id}"  # the notebooks workspace chat's key


class ChatGuard:
    """Checks who may use an assistant and a chat (roles, course permission, rate)."""

    def __init__(
        self, gate: AuthorGate, rate_limiter: RateLimiter, settings: Settings
    ) -> None:
        """Store the course gate, the rate limiter and the limits."""
        self.gate = gate
        self.rate_limiter = rate_limiter
        self.settings = settings

    async def assistant(
        self, actor: Actor, assistant: Assistant, course_id: UUID | None = None
    ) -> None:
        """Check that the actor's roles (and course permission) allow the assistant.

        Raises:
            WrongAssistantError: A role or the course permission is missing.
            CourseRequiredError: The author assistant was asked without a course.
            AuthorUnavailableError: The author assistant is switched off.
        """
        require_assistant_role(actor, assistant)
        if assistant is not Assistant.LMS_AUTHOR:
            return
        if course_id is None:
            raise CourseRequiredError()
        await self.gate.require_editor(actor, course_id)

    @staticmethod
    def mine(actor: Actor, chat: Chat | None) -> Chat:
        """Return the chat if it is the actor's live chat (ownership only).

        Raises:
            ChatNotFoundError: Missing, deleted or someone else's chat.
        """
        if chat is None or chat.deleted_at or chat.owner_id != actor.user_id:
            raise ChatNotFoundError()
        return chat

    async def scope_for(
        self, actor: Actor, assistant: Assistant, course_id: UUID | None
    ) -> ChatScope | None:
        """Check that the actor may start a chat; return the new chat's scope.

        An author chat gets the course and its workspace notebook (created on the
        first chat); the other assistants have no scope (`course_id` is ignored).
        """
        if assistant is not Assistant.LMS_AUTHOR:
            await self.assistant(actor, assistant)
            return None
        if course_id is None:
            raise CourseRequiredError()
        return await self.gate.open_workspace(actor, course_id)

    async def chat(self, actor: Actor, chat: Chat | None) -> Chat:
        """Return the chat if it is the actor's live chat and they may still use it.

        Raises:
            ChatNotFoundError: Missing, deleted or someone else's chat.
            WrongAssistantError: The role or the course permission is gone.
        """
        mine = self.mine(actor, chat)
        await self.assistant(actor, mine.assistant, mine.course_id)
        return mine

    async def owned(self, uow: AiUnitOfWork, actor: Actor, chat_id: UUID) -> Chat:
        """Load the chat in the unit of work and check it (see `chat`)."""
        return await self.chat(actor, await uow.chats.get(chat_id))

    async def admit_message(self, actor: Actor, chat: Chat) -> None:
        """Count a new turn of an author chat against the per-minute limit.

        Raises:
            RateLimitedError: More than ``lms_ai_chat_per_minute`` in a minute.
        """
        if chat.assistant is not Assistant.LMS_AUTHOR:
            return
        await self.rate_limiter.hit(
            COURSE_CHAT_RATE_KEY.format(user_id=actor.user_id),
            limit=self.settings.limits.lms_ai_chat_per_minute,
            window_seconds=RATE_WINDOW_SECONDS,
        )
