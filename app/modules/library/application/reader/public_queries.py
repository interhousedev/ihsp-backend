"""`LibraryQueries` of the contract: lesson links and reading lists for modules."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.library.ports.directories import AcademicDirectory
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor, Role
from app.shared.contracts.library import LessonItemRefView, ReadingListSummary


class LibraryQueriesImpl:
    """Read access for the lesson pages and the subject hub."""

    def __init__(self, *, uow_factory: UowFactory, academic: AcademicDirectory) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory
        self.academic = academic

    async def lesson_item_refs(
        self, lesson_ids: Sequence[UUID]
    ) -> dict[UUID, list[LessonItemRefView]]:
        """Book links of the lessons (lessons without a link are absent)."""
        async with self.uow_factory() as uow:
            return await uow.plans.lesson_refs(lesson_ids)

    async def reading_lists_for_subject(
        self, subject_id: UUID, actor: Actor
    ) -> list[ReadingListSummary]:
        """Published lists of the subject that the actor's group can see."""
        group_id = (
            await self.academic.student_group_id(actor.user_id)
            if Role.STUDENT in actor.roles
            else None
        )
        async with self.uow_factory() as uow:
            return await uow.lists.summaries_for_subject(subject_id, group_id=group_id)
