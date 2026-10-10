"""Filters, sorting and the viewer of a catalogue search (doc §§ 3.7, 7.1)."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal
from uuid import UUID

from app.modules.library.domain.access import is_librarian, is_signed_in
from app.modules.library.domain.enums import ItemType, ShelfState, UploaderRole
from app.modules.library.domain.search_query import ParsedQuery
from app.shared.actor import Actor


class ItemSource(StrEnum):
    """`?source=`: which kinds of item to list."""

    ALL = "all"
    BOOK = "book"
    MATERIAL = "material"
    EXTERNAL = "external"


class ItemSort(StrEnum):
    """`?sort=`; without a query the default is the newest first."""

    RELEVANCE = "relevance"
    NEWEST = "newest"
    TITLE = "title"
    AUTHOR = "author"


@dataclass(frozen=True, slots=True)
class ItemFilters:
    """Everything `GET /library/items` can narrow by."""

    query: ParsedQuery | None = None
    source: ItemSource = ItemSource.ALL
    subject_id: UUID | None = None
    subject_ids: tuple[UUID, ...] = ()
    topic_id: UUID | None = None
    tag: str | None = None
    year_of_study: int | None = None
    type: ItemType | None = None
    language: str | None = None
    collection_id: UUID | None = None
    uploader_role: UploaderRole | None = None
    has_text: bool | None = None
    shelf: ShelfState | Literal["any"] | None = None
    sort: ItemSort = ItemSort.RELEVANCE


@dataclass(frozen=True, slots=True)
class Viewer:
    """The caller as the search sees them: the SQL form of `domain.access.can_view`."""

    user_id: UUID | None = None
    staff: bool = False
    signed_in: bool = False
    anonymous_cards: bool = False
    preferred_subject_ids: tuple[UUID, ...] = ()


@dataclass(frozen=True, slots=True)
class SearchHit:
    """One result: the item and, for a full-text hit, the snippet and its page."""

    item_id: UUID
    snippet: str | None = None
    page: int | None = None


def viewer_from_actor(
    actor: Actor | None,
    *,
    anonymous_cards: bool,
    preferred_subject_ids: tuple[UUID, ...] = (),
) -> Viewer:
    """The viewer of a request."""
    return Viewer(
        user_id=actor.user_id if actor else None,
        staff=is_librarian(actor),
        signed_in=is_signed_in(actor),
        anonymous_cards=anonymous_cards,
        preferred_subject_ids=preferred_subject_ids,
    )
