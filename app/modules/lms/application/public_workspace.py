"""Public API of the course workspace: ``LmsWorkspace`` and ``LmsWorkspaceCommands``.

Providers of the staff side of a course workspace (the AI notebook that belongs to a
course). The notebooks module asks who may open a workspace and reads draft steps as
sources; the author assistant reads the outline and writes through the commands.
"""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.modules.lms.application.authoring.access import (
    access_to,
    load_course,
    load_step,
)
from app.modules.lms.application.authoring.append_block import parse_content
from app.modules.lms.application.authoring.apply_course_plan import ApplyCoursePlan
from app.modules.lms.application.authoring.get_course_draft import GetCourseDraft
from app.modules.lms.application.authoring.save_step_draft import SaveStepDraft
from app.modules.lms.application.authoring.uow_factory import UowFactory
from app.modules.lms.domain.authoring.content_edit import strip_empty_ids
from app.modules.lms.domain.authoring.enums import StepVia
from app.modules.lms.domain.authoring.errors import StepNotFoundError
from app.modules.lms.domain.learning.source_text import export_text
from app.modules.lms.domain.step_content import StepContent
from app.shared.actor import Actor
from app.shared.contracts.identity import IdentityDirectory
from app.shared.contracts.lms import (
    CourseBrief,
    CourseSectionBrief,
    CourseStepBrief,
    CourseWorkspaceAccess,
    LmsStepText,
)


def _via(via_ai: bool) -> StepVia:
    return StepVia.AI if via_ai else StepVia.UI


class LmsWorkspaceImpl:
    """`LmsWorkspace`: access, outline and draft step texts of a course workspace."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        identity: IdentityDirectory,
        get_course_draft: GetCourseDraft,
    ) -> None:
        """Store the unit of work factory, the identity directory and the outline."""
        self._uow_factory = uow_factory
        self._identity = identity
        self._get_course_draft = get_course_draft

    async def course_access(
        self, user_id: UUID, course_id: UUID
    ) -> CourseWorkspaceAccess | None:
        """Return the user's access to the course, or None for a stranger.

        Decided by the same `CourseAccess` as the authoring use cases: an LMS admin
        (global role `lms_admin`) holds every permission, other people the permissions
        of their staff row. Students, strangers and unknown courses give None.
        """
        user = await self._identity.get_user(user_id)
        actor = Actor(user_id=user_id, roles=user.roles if user else frozenset())
        async with self._uow_factory() as uow:
            course = await uow.courses.get(course_id)
            if course is None:
                return None
            access = await access_to(uow, actor, course_id)
        if not access.is_staff:
            return None
        meta = course.draft_meta
        return CourseWorkspaceAccess(
            course_id=course.id,
            title=meta.get("title", course.title),
            description=meta.get("description", course.description),
            permissions=tuple(access.permissions),
        )

    async def course_brief(self, course_id: UUID) -> CourseBrief | None:
        """Return the draft outline of the course; None when it does not exist."""
        view = await self._get_course_draft.unchecked(course_id)
        if view is None:
            return None
        return CourseBrief(
            course_id=view.id,
            title=view.title,
            description=view.description,
            draft_seq=view.draft_seq,
            sections=tuple(
                CourseSectionBrief(
                    section_id=section.id,
                    title=section.title,
                    steps=tuple(
                        CourseStepBrief(step_id=step.step_id, title=step.title)
                        for step in section.steps
                        if step.badge != "removed"  # still live, gone from the draft
                    ),
                )
                for section in view.outline
            ),
        )

    async def draft_step_text(self, course_id: UUID, step_id: UUID) -> LmsStepText:
        """Return the text of a step's draft: text, cards and tests with their keys.

        The workspace belongs to the authors of the course, so the test questions
        come with their correct answers and explanations.

        Raises:
            StepNotFoundError: The step does not belong to the course.
        """
        async with self._uow_factory() as uow:
            step = await load_step(uow, step_id)
            if step.course_id != course_id:
                raise StepNotFoundError(params={"step_id": str(step_id)})
            course = await load_course(uow, course_id)
        text, starts = export_text(
            StepContent.model_validate(step.draft), with_answers=True
        )
        return LmsStepText(
            course_id=course_id,
            course_title=course.draft_meta.get("title", course.title),
            step_id=step_id,
            title=step.title,
            revision_id=step.draft_hash,
            text=text,
            block_starts=starts,
        )


class LmsWorkspaceCommandsImpl:
    """`LmsWorkspaceCommands`: apply a plan to the outline, replace a step's draft."""

    def __init__(
        self, *, apply_course_plan: ApplyCoursePlan, save_step_draft: SaveStepDraft
    ) -> None:
        """Store the use cases that back each command."""
        self._apply_course_plan = apply_course_plan
        self._save_step_draft = save_step_draft

    async def apply_outline(
        self,
        actor: Actor,
        course_id: UUID,
        sections: Sequence[dict[str, Any]],
        *,
        dry_run: bool = False,
        add_briefs: bool = False,
        via_ai: bool = True,
    ) -> dict[str, Any]:
        """Create the sections and steps of a plan that the draft does not have.

        Nothing is renamed, moved or removed; see `LmsWorkspaceCommands.apply_outline`.
        """
        view = await self._apply_course_plan.execute(
            actor,
            course_id,
            sections,
            dry_run=dry_run,
            add_briefs=add_briefs,
            via=_via(via_ai),
        )
        return view.model_dump(mode="json")

    async def replace_step(
        self,
        actor: Actor,
        step_id: UUID,
        content: dict[str, Any],
        lock_version: int,
        *,
        via_ai: bool = True,
    ) -> dict[str, Any]:
        """Replace the draft content of a step; the server assigns the IDs.

        A stale `lock_version` raises `DraftConflictError` whose `params` carry the
        current `lock_version`; invalid content raises `ContentInvalidError`.
        """
        parsed = parse_content(strip_empty_ids(content))
        saved = await self._save_step_draft.execute(
            actor, step_id, parsed, lock_version, via=_via(via_ai)
        )
        return {
            "step_id": str(step_id),
            "blocks": [b.model_dump(mode="json") for b in saved.content.blocks],
            "lock_version": saved.lock_version,
        }
