"""Port: who may use the course author assistant, per course."""

from typing import Protocol
from uuid import UUID

from app.modules.ai.domain.chat_scope import ChatScope
from app.shared.actor import Actor
from app.shared.contracts.lms import CourseBrief


class AuthorGate(Protocol):
    """Course permission checks and the course workspace of author chats.

    The author assistant has no global role: a user may use it on a course where
    they hold the ``edit`` permission (LMS admins hold every permission).
    """

    async def require_editor(self, actor: Actor, course_id: UUID) -> None:
        """Raise unless the feature is on and the actor may edit the course.

        Raises:
            AuthorUnavailableError: The feature is off or not wired.
            WrongAssistantError: Not course staff with ``edit`` (strangers too).
        """
        ...

    async def open_workspace(self, actor: Actor, course_id: UUID) -> ChatScope:
        """Check ``edit``, then return the course's workspace (created if needed)."""
        ...

    async def course_brief(self, course_id: UUID) -> CourseBrief | None:
        """Return the draft outline for the prompt (no access check)."""
        ...
