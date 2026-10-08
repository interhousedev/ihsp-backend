"""Public API of course authoring: the contracts used by the MCP servers."""

from typing import Any
from uuid import UUID

from app.modules.lms.application.authoring.append_block import AppendBlock
from app.modules.lms.application.authoring.append_question import AppendQuestion
from app.modules.lms.application.authoring.create_section import CreateSection
from app.modules.lms.application.authoring.create_step import CreateStep
from app.modules.lms.application.authoring.get_course_draft import GetCourseDraft
from app.modules.lms.application.authoring.get_pending_changes import (
    GetPendingChanges,
)
from app.modules.lms.application.authoring.get_step_draft import GetStepDraft
from app.modules.lms.application.authoring.list_course_attempts import (
    ListCourseAttempts,
)
from app.modules.lms.application.authoring.list_courses_for_staff import (
    ListCoursesForStaff,
)
from app.modules.lms.application.authoring.list_versions import ListVersions
from app.modules.lms.domain.authoring.enums import StepVia
from app.shared.actor import Actor


def _via(via_mcp: bool) -> StepVia:
    return StepVia.MCP if via_mcp else StepVia.UI


class LmsQueriesImpl:
    """`LmsQueries`: read tools for course authors (JSON-compatible dicts)."""

    def __init__(
        self,
        *,
        list_courses: ListCoursesForStaff,
        get_course_draft: GetCourseDraft,
        get_step_draft: GetStepDraft,
        get_pending_changes: GetPendingChanges,
        list_versions: ListVersions,
        list_attempts: ListCourseAttempts,
    ) -> None:
        """Store the use cases that back each query."""
        self._list_courses = list_courses
        self._get_course_draft = get_course_draft
        self._get_step_draft = get_step_draft
        self._get_pending_changes = get_pending_changes
        self._list_versions = list_versions
        self._list_attempts = list_attempts

    async def courses_for_staff(
        self, user_id: UUID, permission: str
    ) -> list[dict[str, Any]]:
        """Return courses where the user holds the permission."""
        return await self._list_courses.execute(user_id, permission)

    async def course_detail(self, course_id: UUID, actor: Actor) -> dict[str, Any]:
        """Return the draft outline and the live version number."""
        view = await self._get_course_draft.execute(actor, course_id)
        return view.model_dump(mode="json")

    async def step_draft(self, step_id: UUID, actor: Actor) -> dict[str, Any]:
        """Return the draft content of a step."""
        view = await self._get_step_draft.execute(actor, step_id)
        return view.model_dump(mode="json")

    async def pending_changes(self, course_id: UUID, actor: Actor) -> dict[str, Any]:
        """Return the unpublished changes of a course."""
        view = await self._get_pending_changes.execute(actor, course_id)
        return view.model_dump(mode="json")

    async def versions(self, course_id: UUID, actor: Actor) -> list[dict[str, Any]]:
        """Return the published versions of a course."""
        items = await self._list_versions.execute(actor, course_id)
        return [item.model_dump(mode="json") for item in items]

    async def attempts(
        self, course_id: UUID, actor: Actor, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Return the latest test attempts; reviewers only."""
        return await self._list_attempts.execute(actor, course_id, limit)


class LmsDraftCommandsImpl:
    """`LmsDraftCommands`: add-only draft edits (MCP-6).

    There is no method to edit, delete, publish or create a course.
    """

    def __init__(
        self,
        *,
        create_section: CreateSection,
        create_step: CreateStep,
        append_block: AppendBlock,
        append_question: AppendQuestion,
    ) -> None:
        """Store the use cases that back each command."""
        self._create_section = create_section
        self._create_step = create_step
        self._append_block = append_block
        self._append_question = append_question

    async def create_section(
        self, actor: Actor, course_id: UUID, title: str, *, via_mcp: bool
    ) -> dict[str, Any]:
        """Add a section at the end of the draft outline."""
        view = await self._create_section.execute(actor, course_id, title)
        return view.model_dump(mode="json")

    async def create_step(
        self,
        actor: Actor,
        course_id: UUID,
        section_id: str,
        title: str,
        *,
        via_mcp: bool,
    ) -> dict[str, Any]:
        """Add an empty step at the end of a section."""
        view = await self._create_step.execute(
            actor, course_id, section_id=section_id, title=title, via=_via(via_mcp)
        )
        return {
            "step_id": str(view.step_id),
            "course_id": str(view.course_id),
            "section_id": section_id,
            "title": view.content.title,
            "lock_version": view.lock_version,
        }

    async def add_block(
        self, actor: Actor, step_id: UUID, block: dict[str, Any], *, via_mcp: bool
    ) -> dict[str, Any]:
        """Append a block to a draft step."""
        return await self._append_block.execute(
            actor, step_id, block, via=_via(via_mcp)
        )

    async def add_question(
        self,
        actor: Actor,
        step_id: UUID,
        block_id: str,
        question: dict[str, Any],
        *,
        via_mcp: bool,
    ) -> dict[str, Any]:
        """Append a question to a test block of a draft step."""
        return await self._append_question.execute(
            actor, step_id, block_id, question, via=_via(via_mcp)
        )
