"""Port: book plans and lesson links (owner: the reader area)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.library.domain.book_plan import BookPlan
from app.shared.contracts.library import LessonItemRefView


@dataclass(frozen=True, slots=True)
class LessonItemRef:
    """A stored link from a lesson to a section of an item."""

    lesson_id: UUID
    item_id: UUID
    section_label: str
    page_from: int | None
    page_to: int | None
    set_by: UUID
    updated_at: datetime


class PlanRepository(Protocol):
    """Textbook plans per subject and year, and the links of lessons to books."""

    async def get_plan(self, subject_id: UUID, year_of_study: int) -> BookPlan | None:
        """The plan of the subject and year (the latest when several exist)."""
        ...

    async def save_plan(self, plan: BookPlan) -> None:
        """Store the plan; any other book's plan of the same subject and year goes."""
        ...

    async def list_lesson_refs(self, lesson_id: UUID) -> list[LessonItemRef]:
        """The links of the lesson in the order the teacher set them."""
        ...

    async def set_lesson_refs(
        self, lesson_id: UUID, refs: Sequence[LessonItemRef]
    ) -> None:
        """Replace all links of the lesson; the order of `refs` is kept."""
        ...

    async def lesson_refs(
        self, lesson_ids: Sequence[UUID]
    ) -> dict[UUID, list[LessonItemRefView]]:
        """Links with item titles for the lessons (lessons without links are absent).

        Only items that are listed (published and not hidden) appear.
        """
        ...

    async def linked_lessons(
        self, lesson_ids: Sequence[UUID]
    ) -> dict[UUID, list[LessonItemRef]]:
        """The stored links of several lessons (lessons without links are absent)."""
        ...
