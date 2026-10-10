"""Read models of the taxonomy area; HTTP schemas map them one to one (doc § 7.5)."""

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from app.modules.library.application.views import ItemCardView, SubjectView
from app.modules.library.domain.enums import (
    Importance,
    ItemStatus,
    ListScope,
    ListStatus,
    ReportReason,
    ShelfState,
)
from app.modules.library.domain.moderation_entities import QueueAgeStats

# - - - Topics - - -


@dataclass(frozen=True, slots=True)
class TopicView:
    """`Topic` of the contract: the name in the reader's language, with children."""

    id: UUID
    subject_id: UUID
    name: str
    slug: str
    year_of_study: int | None
    children: tuple["TopicView", ...]


@dataclass(frozen=True, slots=True)
class ManageTopicView:
    """`ManageTopic`: all three names, for the librarian's editor."""

    id: UUID
    subject_id: UUID
    parent_id: UUID | None
    name: dict[str, str]
    slug: str
    position: int
    year_of_study: int | None
    code: str | None = None
    archived: bool = False


@dataclass(frozen=True, slots=True)
class ManageSubjectView:
    """`ManageSubject`: all three names, the code and the archive flag."""

    id: UUID
    parent_id: UUID | None
    name: dict[str, str]
    slug: str
    code: str | None
    position: int
    archived: bool


# - - - Collections - - -


@dataclass(frozen=True, slots=True)
class CollectionView:
    """`Collection` of the contract."""

    id: UUID
    slug: str
    title: str
    description: str | None
    cover_url: str | None
    item_count: int


@dataclass(frozen=True, slots=True)
class CollectionDetailView:
    """`CollectionDetail`: the collection and its visible items as cards."""

    collection: CollectionView
    items: tuple[ItemCardView, ...]


@dataclass(frozen=True, slots=True)
class ManageCollectionView:
    """`ManageCollection`: all languages and the stored item ids."""

    id: UUID
    slug: str
    title: dict[str, str]
    description: dict[str, str] | None
    cover_url: str | None
    published: bool
    position: int
    item_ids: tuple[UUID, ...]


# - - - Reading lists - - -


@dataclass(frozen=True, slots=True)
class PersonView:
    """The owner of a list as the reader sees them."""

    id: UUID
    name: str


@dataclass(frozen=True, slots=True)
class ReadingListCardView:
    """`ReadingListCard`: counts are of the entries the viewer may see."""

    id: UUID
    title: str
    description: str | None
    scope: ListScope
    status: ListStatus
    subject: SubjectView | None
    year_of_study: int | None
    academic_year: str | None
    term_half: int | None
    owner: PersonView
    entry_count: int
    essential_count: int
    essential_done: int
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ReadingListEntryView:
    """`ReadingListEntry`: an item card or a plain link, with my read status."""

    position: int
    item: ItemCardView | None
    url: str | None
    title: str | None
    importance: Importance
    page_from: int | None
    page_to: int | None
    week_label: str | None
    due_on: date | None
    topic_id: UUID | None
    note: str | None
    read_state: ShelfState | None


@dataclass(frozen=True, slots=True)
class ReadingListDetailView:
    """`ReadingListDetail`: the card, the groups, the entries and what I may do."""

    card: ReadingListCardView
    group_ids: tuple[UUID, ...]
    entries: tuple[ReadingListEntryView, ...]
    can_edit: bool


# - - - Statistics - - -


@dataclass(frozen=True, slots=True)
class UploadDayView:
    """Materials uploaded on one UTC day."""

    day: date
    count: int


@dataclass(frozen=True, slots=True)
class SearchMissView:
    """A query that found nothing, and how often."""

    q: str
    count: int


@dataclass(frozen=True, slots=True)
class TopItemView:
    """A much opened item."""

    item: ItemCardView
    opens: int


@dataclass(frozen=True, slots=True)
class LibraryStatsView:
    """`LibraryStats` of the contract."""

    opens: int
    readers: int
    queue: QueueAgeStats
    uploads_by_day: tuple[UploadDayView, ...]
    searches_without_results: tuple[SearchMissView, ...]
    top_items: tuple[TopItemView, ...]
    items_by_status: dict[ItemStatus, int]
    reports_by_reason: dict[ReportReason, int]
    subjects_without_materials: tuple[SubjectView, ...]
