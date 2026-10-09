"""AuthorGate over the LMS and notebooks contracts (reached through late bindings)."""

from uuid import UUID

from app.modules.ai.application.late_bindings import LateBindings
from app.modules.ai.domain.assistant import Assistant
from app.modules.ai.domain.chat_scope import ChatScope
from app.modules.ai.domain.errors import AuthorUnavailableError, WrongAssistantError
from app.settings import Settings
from app.shared.actor import Actor
from app.shared.contracts.lms import CourseBrief, LmsWorkspace
from app.shared.contracts.notebooks import NotebooksCommands, NotebooksQueries
from app.shared.features import Feature, is_enabled

AUTHOR_FEATURES = (Feature.AI_ASSISTANT, Feature.LMS, Feature.NOTEBOOKS)


class LateAuthorGate:
    """Implements AuthorGate: course permission by LMS, workspace by notebooks.

    Every check asks the LMS again, so a staff member who loses ``edit`` loses the
    assistant on the very next call. Missing collaborators (a process without LMS or
    notebooks) and switched-off features answer with `ai/feature-disabled`.
    """

    def __init__(self, bindings: LateBindings, settings: Settings) -> None:
        """Store the late bindings and the feature switches."""
        self.bindings = bindings
        self.settings = settings

    def _lms(self) -> LmsWorkspace:
        if not all(is_enabled(self.settings, f) for f in AUTHOR_FEATURES):
            raise AuthorUnavailableError(support_details="author features are off")
        if self.bindings.lms_workspace is None:
            raise AuthorUnavailableError(support_details="lms workspace not bound")
        return self.bindings.lms_workspace

    def _notebooks(self) -> tuple[NotebooksQueries, NotebooksCommands]:
        queries, commands = self.bindings.notebooks, self.bindings.notebooks_commands
        if queries is None or commands is None:
            raise AuthorUnavailableError(support_details="notebooks not bound")
        return queries, commands

    async def require_editor(self, actor: Actor, course_id: UUID) -> None:
        """Raise unless the feature is on and the actor may edit the course."""
        access = await self._lms().course_access(actor.user_id, course_id)
        if access is None or not access.can_write:
            raise WrongAssistantError(
                params={"assistant": Assistant.LMS_AUTHOR.value},
                support_details=f"no edit permission on course {course_id}",
            )

    async def open_workspace(self, actor: Actor, course_id: UUID) -> ChatScope:
        """Check ``edit``, then return the course's workspace (created if needed)."""
        await self.require_editor(actor, course_id)
        queries, commands = self._notebooks()
        found = await queries.course_workspace(actor.user_id, course_id)
        if found is None:
            found = await commands.open_course_workspace(actor, course_id)
        return ChatScope(course_id=course_id, notebook_id=UUID(str(found["id"])))

    async def course_brief(self, course_id: UUID) -> CourseBrief | None:
        """Return the draft outline for the prompt (no access check)."""
        return await self._lms().course_brief(course_id)
