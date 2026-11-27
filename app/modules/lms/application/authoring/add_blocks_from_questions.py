"""Use case: put generated questions into a step as one test block."""

from collections.abc import Sequence
from typing import Any, Protocol
from uuid import UUID

from app.modules.lms.application.authoring.uow_factory import UowFactory
from app.modules.notebooks.application.course_convert import questions_to_test_block
from app.shared.actor import Actor
from app.shared.base_error import NotFoundError
from app.shared.contracts.teacher_ai import QuestionItem


class StepCourses(Protocol):
    """Which course a step belongs to."""

    async def course_of(self, step_id: UUID) -> UUID | None:
        """Return the course of the step, None when it does not exist."""
        ...


class BlockAppender(Protocol):
    """Adds a block to a step draft; enforces the `edit` permission."""

    async def execute(
        self,
        actor: Actor,
        step_id: UUID,
        block: dict[str, Any],
        *,
        position: int | None = None,
    ) -> dict[str, Any]:
        """Insert the block at `position` (the end when None)."""
        ...


class UowStepCourses:
    """`StepCourses` over the authoring unit of work."""

    def __init__(self, uow_factory: UowFactory) -> None:
        """Store the unit of work factory."""
        self.uow_factory = uow_factory

    async def course_of(self, step_id: UUID) -> UUID | None:
        """Return the course id of a live step."""
        async with self.uow_factory() as uow:
            step = await uow.steps.get(step_id)
        return None if step is None else step.course_id


class AddBlocksFromQuestions:
    """Turn questions into a test block and append it to a step of the course."""

    def __init__(self, steps: StepCourses, append: BlockAppender) -> None:
        """Store collaborators."""
        self.steps = steps
        self.append = append

    async def execute(
        self,
        actor: Actor,
        course_id: UUID,
        step_id: UUID,
        questions: Sequence[QuestionItem],
        position: int | None,
    ) -> dict[str, Any]:
        """Append the block; a step of another course or a deleted one is not found."""
        if await self.steps.course_of(step_id) != course_id:
            raise NotFoundError()
        block = questions_to_test_block(questions)
        return await self.append.execute(actor, step_id, block, position=position)


class QuestionBlocks:
    """The facade behind `container.lms_authoring` used by the HTTP route."""

    def __init__(self, use_case: AddBlocksFromQuestions) -> None:
        """Store the use case."""
        self.use_case = use_case

    async def add_blocks_from_questions(
        self,
        actor: Actor,
        course_id: UUID,
        step_id: UUID,
        questions: Sequence[QuestionItem],
        position: int | None,
    ) -> dict[str, Any]:
        """Append a test block built from the questions."""
        return await self.use_case.execute(
            actor, course_id, step_id, questions, position
        )
