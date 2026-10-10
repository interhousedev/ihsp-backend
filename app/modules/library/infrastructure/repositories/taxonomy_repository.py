"""SQL repository of topics and collections (taxonomy area)."""

from collections.abc import Collection as AbstractCollection
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.modules.library.domain.taxonomy_collections import Collection
from app.modules.library.domain.taxonomy_subjects import Subject
from app.modules.library.domain.taxonomy_topics import Topic
from app.modules.library.infrastructure.orm import Collection as CollectionRow
from app.modules.library.infrastructure.orm import CollectionItem as CollectionItemRow
from app.modules.library.infrastructure.orm import ItemSubject as ItemSubjectRow
from app.modules.library.infrastructure.orm import ItemTopic as ItemTopicRow
from app.modules.library.infrastructure.orm import Subject as SubjectRow
from app.modules.library.infrastructure.orm import Topic as TopicRow

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

# - - - Row <-> entity - - -


def _topic_from(row: TopicRow) -> Topic:
    return Topic(
        id=row.id,
        subject_id=row.subject_id,
        parent_id=row.parent_id,
        name={k: str(v) for k, v in row.name.items()},
        slug=row.slug,
        position=row.position,
        year_of_study=row.year_of_study,
        created_at=row.created_at,
        updated_at=row.updated_at,
        code=row.code,
        archived_at=row.archived_at,
    )


def _subject_from(row: SubjectRow) -> Subject:
    return Subject(
        id=row.id,
        parent_id=row.parent_id,
        name={k: str(v) for k, v in row.name.items()},
        slug=row.slug,
        position=row.position,
        created_at=row.created_at,
        updated_at=row.updated_at,
        code=row.code,
        archived_at=row.archived_at,
    )


def _apply_subject(row: SubjectRow, subject: Subject) -> None:
    row.parent_id = subject.parent_id
    row.name = dict(subject.name)
    row.slug = subject.slug
    row.code = subject.code
    row.position = subject.position
    row.archived_at = subject.archived_at
    row.updated_at = subject.updated_at


def _apply_topic(row: TopicRow, topic: Topic) -> None:
    row.subject_id = topic.subject_id
    row.parent_id = topic.parent_id
    row.name = dict(topic.name)
    row.slug = topic.slug
    row.position = topic.position
    row.year_of_study = topic.year_of_study
    row.code = topic.code
    row.archived_at = topic.archived_at
    row.updated_at = topic.updated_at


def _collection_from(row: CollectionRow) -> Collection:
    return Collection(
        id=row.id,
        slug=row.slug,
        title={k: str(v) for k, v in row.title.items()},
        description={k: str(v) for k, v in row.description.items()},
        published=row.published,
        position=row.position,
        created_at=row.created_at,
        updated_at=row.updated_at,
        cover_file_id=row.cover_file_id,
    )


def _apply_collection(row: CollectionRow, collection: Collection) -> None:
    row.slug = collection.slug
    row.title = dict(collection.title)
    row.description = dict(collection.description)
    row.cover_file_id = collection.cover_file_id
    row.position = collection.position
    row.published = collection.published
    row.updated_at = collection.updated_at


class SqlTaxonomyRepository:
    """Stores topics and collections in schema `library`."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the unit of work's session."""
        self.session = session

    async def topic_names(
        self, topic_ids: Sequence[UUID]
    ) -> dict[UUID, dict[str, str]]:
        """Names `{uz, ru, en}` of the existing topics (unknown ids are absent)."""
        if not topic_ids:
            return {}
        rows = await self.session.execute(
            select(TopicRow.id, TopicRow.name).where(TopicRow.id.in_(set(topic_ids)))
        )
        names: dict[UUID, dict[str, Any]] = {row[0]: row[1] for row in rows.all()}
        return {
            tid: {k: str(v) for k, v in name.items()} for tid, name in names.items()
        }

    # - - - Subjects - - -

    async def subjects(self, *, include_archived: bool = True) -> list[Subject]:
        """Every subject by parent and position (without the archived when asked)."""
        query = select(SubjectRow).order_by(
            SubjectRow.parent_id.nulls_first(), SubjectRow.position, SubjectRow.slug
        )
        if not include_archived:
            query = query.where(SubjectRow.archived_at.is_(None))
        rows = await self.session.execute(query)
        return [_subject_from(row) for row in rows.scalars()]

    async def get_subject(self, subject_id: UUID) -> Subject | None:
        """The subject or None."""
        row = await self.session.get(SubjectRow, subject_id)
        return _subject_from(row) if row else None

    async def subject_names(
        self, subject_ids: Sequence[UUID]
    ) -> dict[UUID, dict[str, str]]:
        """Names `{uz, ru, en}` of the existing subjects (unknown ids are absent)."""
        if not subject_ids:
            return {}
        rows = await self.session.execute(
            select(SubjectRow.id, SubjectRow.name).where(
                SubjectRow.id.in_(set(subject_ids))
            )
        )
        return {sid: {k: str(v) for k, v in name.items()} for sid, name in rows.all()}

    async def add_subject(self, subject: Subject) -> None:
        """Insert a subject."""
        row = SubjectRow(id=subject.id, created_at=subject.created_at)
        _apply_subject(row, subject)
        self.session.add(row)
        await self.session.flush()

    async def save_subject(self, subject: Subject) -> None:
        """Update names, slug, code, parent, position and the archive flag."""
        row = await self.session.get(SubjectRow, subject.id)
        if row is None:
            raise LookupError(f"subject {subject.id} is not stored")
        _apply_subject(row, subject)
        await self.session.flush()

    async def delete_subject(self, subject_id: UUID) -> None:
        """Delete the subject (children go with it; callers check it is unused)."""
        await self.session.execute(
            delete(SubjectRow).where(SubjectRow.id == subject_id)
        )

    async def count_subject_items(self, subject_ids: AbstractCollection[UUID]) -> int:
        """How many item-to-subject links the subjects have."""
        if not subject_ids:
            return 0
        count = await self.session.scalar(
            select(func.count())
            .select_from(ItemSubjectRow)
            .where(ItemSubjectRow.subject_id.in_(set(subject_ids)))
        )
        return int(count or 0)

    async def count_subject_topics(self, subject_ids: AbstractCollection[UUID]) -> int:
        """How many topics hang under the subjects."""
        if not subject_ids:
            return 0
        count = await self.session.scalar(
            select(func.count())
            .select_from(TopicRow)
            .where(TopicRow.subject_id.in_(set(subject_ids)))
        )
        return int(count or 0)

    # - - - Topics - - -

    async def topics(self, subject_id: UUID | None = None) -> list[Topic]:
        """The topics of one subject, or of all subjects, by position."""
        query = select(TopicRow).order_by(
            TopicRow.subject_id, TopicRow.position, TopicRow.slug
        )
        if subject_id is not None:
            query = query.where(TopicRow.subject_id == subject_id)
        rows = await self.session.execute(query)
        return [_topic_from(row) for row in rows.scalars()]

    async def get_topic(self, topic_id: UUID) -> Topic | None:
        """The topic or None."""
        row = await self.session.get(TopicRow, topic_id)
        return _topic_from(row) if row else None

    async def add_topic(self, topic: Topic) -> None:
        """Insert a topic."""
        row = TopicRow(id=topic.id, created_at=topic.created_at)
        _apply_topic(row, topic)
        self.session.add(row)
        await self.session.flush()

    async def save_topic(self, topic: Topic) -> None:
        """Update name, slug, parent, position and year of a topic."""
        row = await self.session.get(TopicRow, topic.id)
        if row is None:
            raise LookupError(f"topic {topic.id} is not stored")
        _apply_topic(row, topic)
        await self.session.flush()

    async def delete_topic(self, topic_id: UUID) -> None:
        """Delete the topic; its children and item links go with it (cascade)."""
        await self.session.execute(delete(TopicRow).where(TopicRow.id == topic_id))

    async def count_item_links(self, topic_ids: AbstractCollection[UUID]) -> int:
        """How many item-to-topic links the topics have."""
        if not topic_ids:
            return 0
        count = await self.session.scalar(
            select(func.count())
            .select_from(ItemTopicRow)
            .where(ItemTopicRow.topic_id.in_(set(topic_ids)))
        )
        return int(count or 0)

    # - - - Collections - - -

    async def collections(self, *, published_only: bool) -> list[Collection]:
        """Collections by position (only the published ones when asked)."""
        query = select(CollectionRow).order_by(
            CollectionRow.position, CollectionRow.created_at, CollectionRow.id
        )
        if published_only:
            query = query.where(CollectionRow.published.is_(True))
        rows = await self.session.execute(query)
        return [_collection_from(row) for row in rows.scalars()]

    async def get_collection(self, collection_id: UUID) -> Collection | None:
        """The collection or None."""
        row = await self.session.get(CollectionRow, collection_id)
        return _collection_from(row) if row else None

    async def get_collection_by_slug(self, slug: str) -> Collection | None:
        """The collection with this slug or None."""
        row = (
            await self.session.execute(
                select(CollectionRow).where(CollectionRow.slug == slug)
            )
        ).scalar_one_or_none()
        return _collection_from(row) if row else None

    async def add_collection(self, collection: Collection) -> None:
        """Insert a collection (its items are separate)."""
        row = CollectionRow(id=collection.id, created_at=collection.created_at)
        _apply_collection(row, collection)
        self.session.add(row)
        await self.session.flush()

    async def save_collection(self, collection: Collection) -> None:
        """Update title, description, cover, flag and position."""
        row = await self.session.get(CollectionRow, collection.id)
        if row is None:
            raise LookupError(f"collection {collection.id} is not stored")
        _apply_collection(row, collection)
        await self.session.flush()

    async def delete_collection(self, collection_id: UUID) -> None:
        """Delete the collection and its item rows."""
        await self.session.execute(
            delete(CollectionRow).where(CollectionRow.id == collection_id)
        )

    async def collection_item_ids(
        self, collection_ids: Sequence[UUID]
    ) -> dict[UUID, list[UUID]]:
        """Item ids of each collection in order (empty collections are absent)."""
        result: dict[UUID, list[UUID]] = {}
        if not collection_ids:
            return result
        rows = await self.session.execute(
            select(CollectionItemRow.collection_id, CollectionItemRow.item_id)
            .where(CollectionItemRow.collection_id.in_(set(collection_ids)))
            .order_by(CollectionItemRow.collection_id, CollectionItemRow.position)
        )
        for collection_id, item_id in rows.all():
            result.setdefault(collection_id, []).append(item_id)
        return result

    async def set_collection_items(
        self, collection_id: UUID, item_ids: Sequence[UUID]
    ) -> None:
        """Replace the items of the collection, keeping the given order."""
        await self.session.execute(
            delete(CollectionItemRow).where(
                CollectionItemRow.collection_id == collection_id
            )
        )
        for position, item_id in enumerate(dict.fromkeys(item_ids)):
            self.session.add(
                CollectionItemRow(
                    collection_id=collection_id, item_id=item_id, position=position
                )
            )
        await self.session.flush()

    async def next_collection_position(self) -> int:
        """The position that puts a new collection last."""
        highest = await self.session.scalar(select(func.max(CollectionRow.position)))
        return 0 if highest is None else int(highest) + 1
