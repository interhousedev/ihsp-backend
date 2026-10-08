"""Use case: create a step in a section of the draft (UF-LMS-08, MCP-6)."""

from uuid import UUID

from app.modules.lms.application.authoring.access import (
    access_to,
    load_course_locked,
)
from app.modules.lms.application.authoring.outline_editor import record_draft_change
from app.modules.lms.application.authoring.presenter import Presenter
from app.modules.lms.application.authoring.uow_factory import UowFactory
from app.modules.lms.application.authoring.views import StepDraftView
from app.modules.lms.domain.authoring.course_rules import clean_title
from app.modules.lms.domain.authoring.entities import CourseStep
from app.modules.lms.domain.authoring.enums import StepVia
from app.modules.lms.domain.authoring.errors import OutlineError
from app.modules.lms.domain.authoring.outline import add_step, has_section
from app.modules.lms.domain.authoring.permissions import EDIT
from app.modules.lms.domain.step_content import StepContent, canonical_hash
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.ids import new_id


class CreateStep:
    """Create an empty step and put it into the outline under the course lock."""

    def __init__(
        self, uow_factory: UowFactory, clock: Clock, presenter: Presenter
    ) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.presenter = presenter

    async def execute(
        self,
        actor: Actor,
        course_id: UUID,
        *,
        section_id: str,
        title: str,
        position: int | None = None,
        via: StepVia = StepVia.UI,
    ) -> StepDraftView:
        """Create the step; it never conflicts with outline edits of other people."""
        clean = clean_title(title)
        now = self.clock.now()
        async with self.uow_factory() as uow:
            course = await load_course_locked(uow, course_id)
            access = await access_to(uow, actor, course_id)
            access.require(EDIT)
            if not has_section(course.draft_outline, section_id):
                raise OutlineError(
                    params={"reason": "section-not-found", "section_id": section_id}
                )
            content = StepContent.model_validate({"title": clean, "blocks": []})
            step = CourseStep(
                id=new_id(),
                course_id=course_id,
                draft=content.model_dump(mode="json"),
                draft_hash=canonical_hash(content),
                created_via=via,
                draft_updated_via=via,
                draft_updated_by=actor.user_id,
                draft_updated_at=now,
            )
            await uow.steps.add(step)
            record_draft_change(
                course,
                outline=add_step(course.draft_outline, section_id, step.id, position),
                actor_id=actor.user_id,
                now=now,
            )
            await uow.courses.save(course)
            await uow.commit()
        return await self.presenter.step_draft(step)
