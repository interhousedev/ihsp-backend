"""Public API of course authoring: the contracts used by the MCP servers."""

import secrets
from typing import Any
from uuid import UUID

from app.modules.lms.application.authoring.append_block import (
    AppendBlock,
    parse_content,
)
from app.modules.lms.application.authoring.append_question import AppendQuestion
from app.modules.lms.application.authoring.apply_outline_ops import ApplyOutlineOps
from app.modules.lms.application.authoring.archive_course import ArchiveCourse
from app.modules.lms.application.authoring.create_course import CreateCourse
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
from app.modules.lms.application.authoring.save_step_draft import SaveStepDraft
from app.modules.lms.application.authoring.update_course_meta import UpdateCourseMeta
from app.modules.lms.domain.authoring.content_edit import strip_empty_ids
from app.modules.lms.domain.authoring.course_rules import clean_title, slug_from_title
from app.modules.lms.domain.authoring.enums import StepVia, Visibility
from app.modules.lms.domain.authoring.errors import (
    DraftConflictError,
)
from app.modules.lms.domain.authoring.outline import (
    RemoveSection,
    RemoveStep,
    RenameSection,
)
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

    Courses are created, renamed and archived here, modules and steps are created,
    renamed and removed; nothing publishes, and every call is checked against the
    scopes of the token by the use cases.
    """

    def __init__(
        self,
        *,
        create_section: CreateSection,
        create_step: CreateStep,
        append_block: AppendBlock,
        append_question: AppendQuestion,
        create_course: CreateCourse,
        update_course_meta: UpdateCourseMeta,
        archive_course: ArchiveCourse,
        apply_outline_ops: ApplyOutlineOps,
        get_course_draft: GetCourseDraft,
        get_step_draft: GetStepDraft,
        save_step_draft: SaveStepDraft,
    ) -> None:
        """Store the use cases that back each command."""
        self._create_course = create_course
        self._update_course_meta = update_course_meta
        self._archive_course = archive_course
        self._apply_outline_ops = apply_outline_ops
        self._get_course_draft = get_course_draft
        self._get_step_draft = get_step_draft
        self._save_step_draft = save_step_draft
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

    async def create_course(
        self,
        actor: Actor,
        *,
        title: str,
        slug: str | None,
        visibility: str,
    ) -> dict[str, Any]:
        """Create a course; without a slug one is made from the title."""
        chosen = slug or slug_from_title(title, secrets.token_hex(3))
        view = await self._create_course.execute(
            actor, title=title, slug=chosen, visibility=Visibility(visibility)
        )
        return view.model_dump(mode="json")

    async def update_course(
        self,
        actor: Actor,
        course_id: UUID,
        *,
        title: str | None,
        description: str | None,
    ) -> dict[str, Any]:
        """Change the title and/or description; retried once on a version conflict."""
        try:
            return await self._update_course_once(actor, course_id, title, description)
        except DraftConflictError:
            return await self._update_course_once(actor, course_id, title, description)

    async def _update_course_once(
        self,
        actor: Actor,
        course_id: UUID,
        title: str | None,
        description: str | None,
    ) -> dict[str, Any]:
        current = await self._get_course_draft.execute(actor, course_id)
        view = await self._update_course_meta.execute(
            actor,
            course_id,
            title=current.title if title is None else title,
            description=current.description if description is None else description,
            lock_version=current.lock_version,
        )
        return view.model_dump(mode="json")

    async def delete_course(self, actor: Actor, course_id: UUID) -> dict[str, Any]:
        """Archive the course."""
        status = await self._archive_course.execute(actor, course_id)
        return {"course_id": str(course_id), "status": status.value}

    async def update_module(
        self, actor: Actor, course_id: UUID, section_id: str, title: str
    ) -> dict[str, Any]:
        """Rename a section."""
        op = RenameSection(op="rename_section", section_id=section_id, title=title)
        view = await self._apply_outline_ops.execute(
            actor, course_id, [op], lock_version=None
        )
        return view.model_dump(mode="json")

    async def delete_module(
        self, actor: Actor, course_id: UUID, section_id: str
    ) -> dict[str, Any]:
        """Remove an empty section."""
        op = RemoveSection(op="remove_section", section_id=section_id)
        view = await self._apply_outline_ops.execute(
            actor, course_id, [op], lock_version=None
        )
        return view.model_dump(mode="json")

    async def update_step(
        self,
        actor: Actor,
        step_id: UUID,
        *,
        title: str | None,
        blocks: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        """Rename and/or rewrite a step; retried once on a version conflict."""
        try:
            return await self._update_step_once(actor, step_id, title, blocks)
        except DraftConflictError:
            return await self._update_step_once(actor, step_id, title, blocks)

    async def _update_step_once(
        self,
        actor: Actor,
        step_id: UUID,
        title: str | None,
        blocks: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        current = await self._get_step_draft.execute(actor, step_id)
        raw = current.content.model_dump(mode="json")
        if title is not None:
            raw["title"] = clean_title(title)
        if blocks is not None:
            raw["blocks"] = [strip_empty_ids(block) for block in blocks]
        saved = await self._save_step_draft.execute(
            actor, step_id, parse_content(raw), current.lock_version, via=StepVia.MCP
        )
        return {
            "step_id": str(step_id),
            "title": saved.content.title,
            "blocks": len(saved.content.blocks),
            "lock_version": saved.lock_version,
        }

    async def delete_step(self, actor: Actor, step_id: UUID) -> dict[str, Any]:
        """Take the step out of the outline."""
        current = await self._get_step_draft.execute(actor, step_id)
        op = RemoveStep(op="remove_step", step_id=step_id)
        await self._apply_outline_ops.execute(
            actor, current.course_id, [op], lock_version=None
        )
        return {"step_id": str(step_id), "course_id": str(current.course_id)}
