"""Factories of the taxonomy tests: topics, collections, reading lists."""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

from app.modules.library.domain.enums import (
    Importance,
    ListScope,
    ListStatus,
)
from app.modules.library.domain.reading_list import ReadingList, ReadingListEntry
from app.modules.library.domain.taxonomy_collections import Collection
from app.modules.library.domain.taxonomy_topics import Topic
from app.shared.ids import new_id

NOW = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)


def make_topic(
    subject_id: UUID,
    name: str = "Mechanics",
    *,
    parent_id: UUID | None = None,
    position: int = 0,
    slug: str | None = None,
    year_of_study: int | None = None,
) -> Topic:
    """A stored-ready topic with the same name in all languages."""
    return Topic(
        id=new_id(),
        subject_id=subject_id,
        parent_id=parent_id,
        name={"uz": name, "ru": name, "en": name},
        slug=slug or name.lower().replace(" ", "-"),
        position=position,
        year_of_study=year_of_study,
        created_at=NOW,
        updated_at=NOW,
    )


def make_collection(
    title: str = "Uzbek classics",
    *,
    published: bool = True,
    position: int = 0,
    slug: str | None = None,
) -> Collection:
    """A collection with the same title in all languages."""
    return Collection(
        id=new_id(),
        slug=slug or title.lower().replace(" ", "-"),
        title={"uz": title, "ru": title, "en": title},
        description={},
        published=published,
        position=position,
        created_at=NOW,
        updated_at=NOW,
    )


def make_reading_list(
    owner_id: UUID,
    *,
    title: str = "Required reading",
    scope: ListScope = ListScope.SUBJECT,
    status: ListStatus = ListStatus.PUBLISHED,
    subject_id: UUID | None = None,
    group_ids: list[UUID] | None = None,
    updated_at: datetime = NOW,
) -> ReadingList:
    """A reading list in any state."""
    return ReadingList(
        id=new_id(),
        owner_id=owner_id,
        title=title,
        scope=scope,
        status=status,
        created_at=NOW,
        updated_at=updated_at,
        subject_id=subject_id,
        group_ids=group_ids or [],
        academic_year="2026-2027",
    )


def item_entry(
    position: int,
    item_id: UUID,
    importance: Importance = Importance.RECOMMENDED,
    **fields: object,
) -> ReadingListEntry:
    """An entry that points at a library item."""
    base = ReadingListEntry(position=position, importance=importance, item_id=item_id)
    return replace(base, **fields)


def link_entry(
    position: int,
    url: str = "https://example.org/read",
    importance: Importance = Importance.RECOMMENDED,
) -> ReadingListEntry:
    """An entry that points at a web page."""
    return ReadingListEntry(
        position=position, importance=importance, url=url, title=url
    )
