"""Use case: create the sections and steps of a plan that the draft lacks (LMS-6)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.lms.application.authoring.access import (
    access_to,
    load_course,
    load_course_locked,
)
from app.modules.lms.application.authoring.draft_writer import StepDraftWriter
from app.modules.lms.application.authoring.outline_editor import record_draft_change
from app.modules.lms.application.authoring.uow_factory import UowFactory
from app.modules.lms.application.authoring.views import (
    CreatedSectionView,
    CreatedStepView,
    PlanAppliedView,
    PlannedSectionView,
    PlannedStepView,
)
from app.modules.lms.domain.authoring.course_plan import (
    PlanAction,
    SectionPlan,
    StepPlan,
    match_plan,
    parse_plan,
)
from app.modules.lms.domain.authoring.entities import Course, CourseStep
from app.modules.lms.domain.authoring.enums import StepVia
from app.modules.lms.domain.authoring.outline import (
    AddSection,
    Outline,
    add_step,
    apply_ops,
    step_ids_in,
)
from app.modules.lms.domain.authoring.permissions import EDIT
from app.modules.lms.domain.step_content import StepContent
from app.modules.lms.ports.authoring.unit_of_work import AuthoringUnitOfWork
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.ids import new_id


@dataclass(slots=True)
class _Created:
    """What one call created, in plan order."""

    sections: list[CreatedSectionView] = field(default_factory=list)
    steps: list[CreatedStepView] = field(default_factory=list)


class ApplyCoursePlan:
    """Add what a plan has and the draft outline does not, in one transaction.

    The course row is locked first and `draft_seq` is bumped once for the whole plan.
    Existing sections and steps are found by title and left alone; a second identical
    call creates nothing and does not touch the draft.
    """

    def __init__(
        self, uow_factory: UowFactory, clock: Clock, writer: StepDraftWriter
    ) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.writer = writer

    async def execute(
        self,
        actor: Actor,
        course_id: UUID,
        sections: Sequence[Mapping[str, Any]],
        *,
        dry_run: bool,
        add_briefs: bool,
        via: StepVia,
    ) -> PlanAppliedView:
        """Apply the plan, or with `dry_run` only report what it would do.

        With `add_briefs` a *new* step starts with its brief as a text block.
        """
        planned = parse_plan(sections)
        created = _Created()
        async with self.uow_factory() as uow:
            course = await (load_course if dry_run else load_course_locked)(
                uow, course_id
            )
            (await access_to(uow, actor, course_id)).require(EDIT)
            steps = await uow.steps.get_many(step_ids_in(course.draft_outline))
            plan = match_plan(
                course.draft_outline, {i: s.title for i, s in steps.items()}, planned
            )
            if not dry_run and _has_new(plan):
                outline = self._add_sections(course, plan, created)
                now = self.clock.now()
                for section in plan:
                    outline = await self._add_steps(
                        uow,
                        course,
                        section,
                        outline,
                        created,
                        actor,
                        via,
                        now,
                        add_briefs=add_briefs,
                    )
                record_draft_change(
                    course, outline=outline, actor_id=actor.user_id, now=now
                )
                await uow.courses.save(course)
                await uow.commit()
            return _view(plan, created, course.draft_seq)

    @staticmethod
    def _add_sections(
        course: Course, plan: Sequence[SectionPlan], created: _Created
    ) -> Outline:
        """Append the new sections to a copy of the outline and note their IDs."""
        new = [s for s in plan if s.action is PlanAction.NEW]
        ops = [AddSection(op="add_section", title=s.title) for s in new]
        outline, ids = apply_ops(course.draft_outline, ops, course_step_ids=())
        for section, section_id in zip(new, ids, strict=True):
            section.section_id = section_id
            created.sections.append(
                CreatedSectionView(id=section_id, title=section.title)
            )
        return outline

    async def _add_steps(
        self,
        uow: AuthoringUnitOfWork,
        course: Course,
        section: SectionPlan,
        outline: Outline,
        created: _Created,
        actor: Actor,
        via: StepVia,
        now: datetime,
        *,
        add_briefs: bool,
    ) -> Outline:
        """Create the new steps of one section and put them at its end."""
        section_id = section.section_id or ""
        for step in section.steps:
            if step.action is not PlanAction.NEW:
                continue
            row = await self._new_step(course.id, step, actor, via, now, add_briefs)
            await uow.steps.add(row)
            outline = add_step(outline, section_id, row.id, None)
            step.step_id = row.id
            created.steps.append(
                CreatedStepView(step_id=row.id, section_id=section_id, title=step.title)
            )
        return outline

    async def _new_step(
        self,
        course_id: UUID,
        step: StepPlan,
        actor: Actor,
        via: StepVia,
        now: datetime,
        add_briefs: bool,
    ) -> CourseStep:
        brief = step.brief if add_briefs else ""
        blocks = [{"type": "text", "markdown": brief}] if brief else []
        content = StepContent.model_validate({"title": step.title, "blocks": blocks})
        prepared = await self.writer.prepare_new(content)
        return CourseStep(
            id=new_id(),
            course_id=course_id,
            draft=prepared.content,
            draft_hash=prepared.content_hash,
            created_via=via,
            draft_updated_via=via,
            draft_updated_by=actor.user_id,
            draft_updated_at=now,
            file_ids=prepared.file_ids,
        )


def _has_new(plan: Sequence[SectionPlan]) -> bool:
    return any(
        s.action is PlanAction.NEW
        or any(step.action is PlanAction.NEW for step in s.steps)
        for s in plan
    )


def _view(
    plan: Sequence[SectionPlan], created: _Created, draft_seq: int
) -> PlanAppliedView:
    return PlanAppliedView(
        created_sections=created.sections,
        created_steps=created.steps,
        existing_sections=sum(1 for s in plan if s.action is PlanAction.EXISTS),
        existing_steps=sum(
            1 for s in plan for step in s.steps if step.action is PlanAction.EXISTS
        ),
        plan=[
            PlannedSectionView(
                title=s.title,
                section_id=s.section_id,
                action=s.action.value,
                steps=[
                    PlannedStepView(
                        title=step.title, step_id=step.step_id, action=step.action.value
                    )
                    for step in s.steps
                ],
            )
            for s in plan
        ],
        draft_seq=draft_seq,
    )
