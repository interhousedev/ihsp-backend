"""Read models of the reader state area; HTTP schemas map them one to one."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.modules.library.application.views import ItemCardView
from app.modules.library.domain.book_plan import PlanSection
from app.modules.library.domain.enums import ShelfState


@dataclass(frozen=True, slots=True)
class Paged[T]:
    """`items` and the cursor of the following page (None on the last page)."""

    items: list[T]
    next_cursor: str | None = None


@dataclass(frozen=True, slots=True)
class ShelfEntryView:
    """`ShelfEntry` of the contract: the card, the state and whether it was removed."""

    item: ItemCardView
    state: ShelfState
    finished_at: datetime | None
    updated_at: datetime
    removed: bool


@dataclass(frozen=True, slots=True)
class MeLibraryView:
    """`MeLibrary` of the contract: continue reading, shelf counts, offline limits."""

    continue_reading: list[ItemCardView]
    shelf_counts: dict[ShelfState, int]
    offline_max_items: int
    offline_max_bytes: int


@dataclass(frozen=True, slots=True)
class BookPlanView:
    """The textbook plan of a subject and year with the title of the book."""

    subject_id: UUID
    year_of_study: int
    item_id: UUID
    item_title: str
    sections: tuple[PlanSection, ...]
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class NextSectionView:
    """The suggested section for a lesson: the one after the last linked."""

    item_id: UUID
    item_title: str
    section: PlanSection
