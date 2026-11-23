"""Use case: hand the hidden tests of a graded code block to its enrolled student.

The step view never carries hidden test code. When the student submits, the
browser asks for it and runs it in the sandboxed code runner. Grading is done
on the client, so a determined student can read these tests (accepted risk;
the route is rate limited and only serves graded code blocks of live steps).
"""

from uuid import UUID

from app.modules.lms.application.learning.audience import AudienceGate
from app.modules.lms.application.learning.next_card import require_enrolled
from app.modules.lms.application.learning.revision_loading import load_revision
from app.modules.lms.application.learning.types import UowFactory
from app.modules.lms.application.learning.views import (
    LearningCodeTestView,
    LearningHiddenTestsView,
)
from app.modules.lms.domain.learning.errors import (
    BlockNotFoundError,
    CourseNotFoundError,
)
from app.modules.lms.domain.step_content import CodeBlock
from app.shared.actor import Actor


class GetHiddenTests:
    """Return the hidden tests of a graded code block of the live step."""

    def __init__(self, uow_factory: UowFactory, gate: AudienceGate) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.gate = gate

    async def execute(
        self, actor: Actor, course_id: UUID, step_id: UUID, block_id: str
    ) -> LearningHiddenTestsView:
        """Load the block and return its hidden tests."""
        async with self.uow_factory() as uow:
            context = await require_enrolled(uow, actor, step_id, self.gate)
            if context.course.id != course_id:
                raise CourseNotFoundError(params={"course_id": str(course_id)})
            revision = await load_revision(uow, context.live_step.revision_id)
        block = next(
            (
                b
                for b in revision.content.blocks
                if isinstance(b, CodeBlock) and b.id == block_id and b.graded
            ),
            None,
        )
        if block is None:
            raise BlockNotFoundError(params={"block_id": block_id})
        return LearningHiddenTestsView(
            tests=[
                LearningCodeTestView(
                    id=test.id, name=test.name, code=test.code, hidden=True
                )
                for test in block.tests
                if test.hidden
            ]
        )
