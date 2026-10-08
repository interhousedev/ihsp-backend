"""Use case: render a step draft as a student would see it (LMS-8, UF-LMS-09)."""

from typing import Any
from uuid import UUID

from app.modules.lms.application.authoring.access import access_to, load_step
from app.modules.lms.application.authoring.uow_factory import UowFactory
from app.modules.lms.application.authoring.views import PreviewStepView
from app.modules.lms.domain.authoring.errors import StepNotFoundError
from app.modules.lms.domain.authoring.permissions import VIEW_DRAFTS
from app.modules.lms.domain.learning.points import block_max_points, sum_points
from app.modules.lms.domain.step_content import StepContent, TestBlock
from app.modules.lms.domain.student_render import render_step
from app.shared.actor import Actor


class PreviewStep:
    """Student render of a draft: no correct answers, no explanations."""

    def __init__(self, uow_factory: UowFactory) -> None:
        """Store the unit of work factory."""
        self.uow_factory = uow_factory

    async def execute(
        self, actor: Actor, course_id: UUID, step_id: UUID
    ) -> PreviewStepView:
        """Render the draft; its hash stands in for the revision ID.

        Preview attempts use a real `preview` revision, which the learning side
        asks for through `EnsurePreviewRevision`.
        """
        async with self.uow_factory() as uow:
            step = await load_step(uow, step_id)
            if step.course_id != course_id:
                raise StepNotFoundError(params={"step_id": str(step_id)})
            access = await access_to(uow, actor, course_id)
            access.require(VIEW_DRAFTS)
        content = StepContent.model_validate(step.draft)
        rendered = render_step(content, revision_id=step.draft_hash)
        points = sum_points(
            block_max_points(block)
            for block in content.blocks
            if isinstance(block, TestBlock)
        )
        return PreviewStepView(
            step_id=step.id,
            revision_id=rendered["revision_id"],
            title=rendered["title"],
            blocks=_unpassed(content, rendered["blocks"]),
            completed=False,
            preview=True,
            blocks_total=len(content.blocks),
            points_total=float(points),
        )


def _unpassed(
    content: StepContent, blocks: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Add the learner fields to the render: nothing passed, points of tests."""
    result: list[dict[str, Any]] = []
    for block, rendered in zip(content.blocks, blocks, strict=True):
        extra: dict[str, Any] = {"passed": False}
        if isinstance(block, TestBlock):
            extra |= {
                "points_total": float(block_max_points(block)),
                "points_earned": 0.0,
            }
        result.append({**rendered, **extra})
    return result
