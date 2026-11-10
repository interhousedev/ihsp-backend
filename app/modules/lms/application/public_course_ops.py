"""Public API of course operations for the LMS MCP: ``LmsCourseOps``."""

from collections.abc import Callable, Sequence
from typing import Any
from uuid import UUID

from app.modules.lms.application.authoring.add_course_staff import AddCourseStaff
from app.modules.lms.application.authoring.append_block import parse_content
from app.modules.lms.application.authoring.apply_course_plan import ApplyCoursePlan
from app.modules.lms.application.authoring.apply_outline_ops import ApplyOutlineOps
from app.modules.lms.application.authoring.get_course_settings import (
    GetCourseSettings,
)
from app.modules.lms.application.authoring.get_pending_changes import (
    GetPendingChanges,
)
from app.modules.lms.application.authoring.get_step_draft import GetStepDraft
from app.modules.lms.application.authoring.list_course_staff import ListCourseStaff
from app.modules.lms.application.authoring.publish_course import PublishCourse
from app.modules.lms.application.authoring.remove_course_staff import (
    RemoveCourseStaff,
)
from app.modules.lms.application.authoring.restore_version import RestoreVersion
from app.modules.lms.application.authoring.save_step_draft import SaveStepDraft
from app.modules.lms.application.authoring.update_course_settings import (
    UpdateCourseSettings,
)
from app.modules.lms.application.learning.get_attempt import GetAttempt
from app.modules.lms.application.learning.list_course_students import (
    ListCourseStudents,
)
from app.modules.lms.application.learning.override_score import OverrideScore
from app.modules.lms.domain.authoring.content_edit import (
    strip_empty_ids,
    with_block_moved,
    with_block_removed,
    with_block_replaced,
    with_question_moved,
    with_question_removed,
    with_question_replaced,
)
from app.modules.lms.domain.authoring.enums import StepVia, Visibility
from app.modules.lms.domain.authoring.errors import DraftConflictError
from app.modules.lms.domain.authoring.outline import MoveSection, MoveStep
from app.modules.lms.domain.authoring.unset import UNSET
from app.shared.actor import Actor

Edit = Callable[[dict[str, Any]], dict[str, Any]]


def _with_blocks(blocks: list[Any]) -> Edit:
    """An edit that replaces the blocks of a step."""

    def edit(raw: dict[str, Any]) -> dict[str, Any]:
        return {**raw, "blocks": blocks}

    return edit


class LmsCourseOpsImpl:
    """`LmsCourseOps`: structure, block edits, publishing, staff and grading."""

    def __init__(
        self,
        *,
        apply_outline_ops: ApplyOutlineOps,
        apply_course_plan: ApplyCoursePlan,
        get_step_draft: GetStepDraft,
        save_step_draft: SaveStepDraft,
        get_pending_changes: GetPendingChanges,
        publish_course: PublishCourse,
        restore_version: RestoreVersion,
        get_course_settings: GetCourseSettings,
        update_course_settings: UpdateCourseSettings,
        list_course_staff: ListCourseStaff,
        add_course_staff: AddCourseStaff,
        remove_course_staff: RemoveCourseStaff,
        list_course_students: ListCourseStudents,
        get_attempt: GetAttempt,
        override_score: OverrideScore,
    ) -> None:
        """Store the use cases that back each operation."""
        self._outline = apply_outline_ops
        self._plan = apply_course_plan
        self._get_step = get_step_draft
        self._save_step = save_step_draft
        self._pending = get_pending_changes
        self._publish = publish_course
        self._restore = restore_version
        self._get_settings = get_course_settings
        self._update_settings = update_course_settings
        self._list_staff = list_course_staff
        self._add_staff = add_course_staff
        self._remove_staff = remove_course_staff
        self._students = list_course_students
        self._get_attempt = get_attempt
        self._override = override_score

    async def move_section(
        self, actor: Actor, course_id: UUID, section_id: str, position: int
    ) -> dict[str, Any]:
        """Move a section; returns the draft outline."""
        op = MoveSection(op="move_section", section_id=section_id, position=position)
        view = await self._outline.execute(actor, course_id, [op], lock_version=None)
        return view.model_dump(mode="json")

    async def move_step(
        self,
        actor: Actor,
        course_id: UUID,
        step_id: UUID,
        to_section_id: str,
        position: int,
    ) -> dict[str, Any]:
        """Move a step into a section at a position; returns the draft outline."""
        op = MoveStep(
            op="move_step",
            step_id=step_id,
            to_section_id=to_section_id,
            position=position,
        )
        view = await self._outline.execute(actor, course_id, [op], lock_version=None)
        return view.model_dump(mode="json")

    async def update_block(
        self, actor: Actor, step_id: UUID, block_id: str, block: dict[str, Any]
    ) -> dict[str, Any]:
        """Replace a block, keeping its place and ID."""
        return await self._edit(
            actor, step_id, lambda raw: with_block_replaced(raw, block_id, block)
        )

    async def delete_block(
        self, actor: Actor, step_id: UUID, block_id: str
    ) -> dict[str, Any]:
        """Remove a block."""
        return await self._edit(
            actor, step_id, lambda raw: with_block_removed(raw, block_id)
        )

    async def move_block(
        self, actor: Actor, step_id: UUID, block_id: str, position: int
    ) -> dict[str, Any]:
        """Move a block to a position."""
        return await self._edit(
            actor, step_id, lambda raw: with_block_moved(raw, block_id, position)
        )

    async def update_question(
        self,
        actor: Actor,
        step_id: UUID,
        block_id: str,
        question_id: str,
        question: dict[str, Any],
    ) -> dict[str, Any]:
        """Replace a question, keeping its place and ID."""
        return await self._edit(
            actor,
            step_id,
            lambda raw: with_question_replaced(raw, block_id, question_id, question),
        )

    async def delete_question(
        self, actor: Actor, step_id: UUID, block_id: str, question_id: str
    ) -> dict[str, Any]:
        """Remove a question."""
        return await self._edit(
            actor,
            step_id,
            lambda raw: with_question_removed(raw, block_id, question_id),
        )

    async def move_question(
        self,
        actor: Actor,
        step_id: UUID,
        block_id: str,
        question_id: str,
        position: int,
    ) -> dict[str, Any]:
        """Move a question to a position."""
        return await self._edit(
            actor,
            step_id,
            lambda raw: with_question_moved(raw, block_id, question_id, position),
        )

    async def build_course(
        self,
        actor: Actor,
        course_id: UUID,
        sections: Sequence[dict[str, Any]],
    ) -> dict[str, Any]:
        """Create sections and steps, then fill the new steps with their blocks."""
        plan = [
            {
                "title": section.get("title"),
                "steps": [{"title": step.get("title")} for step in section["steps"]],
            }
            for section in sections
        ]
        applied = await self._plan.execute(
            actor, course_id, plan, dry_run=False, add_briefs=False, via=StepVia.MCP
        )
        result = applied.model_dump(mode="json")
        filled: list[dict[str, Any]] = []
        for section, planned in zip(sections, result["plan"], strict=False):
            for step, done in zip(section["steps"], planned["steps"], strict=False):
                blocks = step.get("blocks")
                if done["action"] != "new" or not blocks:
                    continue
                saved = await self._edit(
                    actor, UUID(str(done["step_id"])), _with_blocks(list(blocks))
                )
                filled.append(saved)
        result["filled"] = filled
        return result

    async def publish(
        self, actor: Actor, course_id: UUID, note: str | None
    ) -> dict[str, Any]:
        """Publish the draft as it is now."""
        pending = await self._pending.execute(actor, course_id)
        version = await self._publish.execute(
            actor, course_id, draft_seq=pending.draft_seq, note=note
        )
        return version.model_dump(mode="json")

    async def restore_version(
        self, actor: Actor, course_id: UUID, number: int
    ) -> dict[str, Any]:
        """Copy an earlier version into the draft."""
        view = await self._restore.execute(actor, course_id, number)
        return view.model_dump(mode="json")

    async def settings(self, actor: Actor, course_id: UUID) -> dict[str, Any]:
        """Return the course settings."""
        view = await self._get_settings.execute(actor, course_id)
        return view.model_dump(mode="json")

    async def update_settings(
        self,
        actor: Actor,
        course_id: UUID,
        *,
        visibility: str | None,
        cover_file_id: UUID | None,
        clear_cover: bool,
    ) -> dict[str, Any]:
        """Change visibility and/or the cover."""
        cover = None if clear_cover else (cover_file_id or UNSET)
        view = await self._update_settings.execute(
            actor,
            course_id,
            visibility=Visibility(visibility) if visibility else None,
            cover_file_id=cover,
        )
        return view.model_dump(mode="json")

    async def list_staff(self, actor: Actor, course_id: UUID) -> list[dict[str, Any]]:
        """List the staff."""
        items = await self._list_staff.execute(actor, course_id)
        return [item.model_dump(mode="json") for item in items]

    async def add_staff(
        self,
        actor: Actor,
        course_id: UUID,
        *,
        login: str,
        role: str,
        permissions: Sequence[str] | None,
    ) -> dict[str, Any]:
        """Add a member by login."""
        item = await self._add_staff.execute(
            actor, course_id, login=login, role=role, permissions=permissions
        )
        return item.model_dump(mode="json")

    async def remove_staff(
        self, actor: Actor, course_id: UUID, user_id: UUID
    ) -> dict[str, Any]:
        """Remove a member."""
        await self._remove_staff.execute(actor, course_id, user_id)
        return {"course_id": str(course_id), "user_id": str(user_id)}

    async def students(self, actor: Actor, course_id: UUID) -> list[dict[str, Any]]:
        """List the students of the course."""
        items = await self._students.execute(actor, course_id)
        return [item.model_dump(mode="json") for item in items]

    async def attempt(self, actor: Actor, attempt_id: UUID) -> dict[str, Any]:
        """Return one attempt."""
        view = await self._get_attempt.execute(actor, attempt_id)
        return view.model_dump(mode="json")

    async def override_score(
        self, actor: Actor, attempt_id: UUID, score: float, comment: str
    ) -> dict[str, Any]:
        """Override the score of an attempt."""
        view = await self._override.execute(actor, attempt_id, score, comment)
        return view.model_dump(mode="json")

    async def _edit(self, actor: Actor, step_id: UUID, edit: Edit) -> dict[str, Any]:
        """Edit the step content as a dict; retried once on a version conflict."""
        try:
            return await self._edit_once(actor, step_id, edit)
        except DraftConflictError:
            return await self._edit_once(actor, step_id, edit)

    async def _edit_once(
        self, actor: Actor, step_id: UUID, edit: Edit
    ) -> dict[str, Any]:
        current = await self._get_step.execute(actor, step_id)
        raw = edit(current.content.model_dump(mode="json"))
        saved = await self._save_step.execute(
            actor,
            step_id,
            parse_content(strip_empty_ids(raw)),
            current.lock_version,
            via=StepVia.MCP,
        )
        return {
            "step_id": str(step_id),
            "title": saved.content.title,
            "blocks": [b.model_dump(mode="json") for b in saved.content.blocks],
            "lock_version": saved.lock_version,
        }
