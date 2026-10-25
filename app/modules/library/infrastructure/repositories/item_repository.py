"""SQL repository of items, their details, files, tags and history."""

from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.library.domain.catalogue_search import (
    ItemFilters,
    SearchHit,
    Viewer,
)
from app.modules.library.domain.entities import (
    BookDetails,
    ExternalDetails,
    Item,
    ItemEvent,
    ItemFile,
    MaterialDetails,
    SubjectLink,
    TopicLink,
)
from app.modules.library.domain.enums import (
    Approval,
    EventKind,
    ExternalAccess,
    ExternalSource,
    FileFormat,
    ItemKind,
    ItemLanguage,
    ItemStatus,
    ItemType,
    MaterialLicence,
    Rights,
    SubjectRole,
    TextStatus,
    UploaderRole,
    Visibility,
)
from app.modules.library.infrastructure import orm
from app.modules.library.infrastructure.orm import BookDetails as BookRow
from app.modules.library.infrastructure.orm import ExternalDetails as ExternalRow
from app.modules.library.infrastructure.orm import Item as ItemRow
from app.modules.library.infrastructure.orm import ItemEvent as EventRow
from app.modules.library.infrastructure.orm import ItemFile as FileRow
from app.modules.library.infrastructure.orm import ItemSubject as SubjectRow
from app.modules.library.infrastructure.orm import ItemTopic as TopicRow
from app.modules.library.infrastructure.orm import MaterialDetails as MaterialRow
from app.modules.library.infrastructure.repositories import item_search

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

ANY_YEAR = 0  # primary-key sentinel for "any year of study"
WHOLE_ITEM = 0  # primary-key sentinel for "the whole item" in topic links

# - - - Row <-> entity - - -


def _apply_item(row: ItemRow, item: Item) -> None:
    row.slug = item.slug
    row.kind = item.kind.value
    row.type = item.type.value
    row.title = item.title
    row.title_alt = dict(item.title_alt)
    row.subtitle = item.subtitle
    row.authors = list(item.authors)
    row.author_label = item.author_label
    row.language = item.language.value
    row.year_published = item.year_published
    row.publisher = item.publisher
    row.isbn = item.isbn
    row.description = item.description
    row.cover_file_id = item.cover_file_id
    row.cover_url = item.cover_url
    row.years_of_study = list(item.years_of_study)
    row.status = item.status.value
    row.status_reason = item.status_reason
    row.status_note = item.status_note
    row.visibility = item.visibility.value
    row.download_allowed = item.download_allowed
    row.has_text = item.has_text
    row.page_count = item.page_count
    row.search_text = item.search_text
    row.content_hash = item.content_hash
    row.owner_id = item.owner_id
    row.reviewed_by = item.reviewed_by
    row.reviewed_at = item.reviewed_at
    row.published_at = item.published_at
    row.supersedes_id = item.supersedes_id
    row.open_reports = item.open_reports
    row.created_by = item.created_by
    row.updated_at = item.updated_at


def _apply_external(row: ExternalRow, details: ExternalDetails) -> None:
    row.source = details.source.value
    row.external_id = details.external_id
    row.category = details.category
    row.access = details.access.value
    row.type_name = dict(details.type_name)
    row.field_name = dict(details.field_name)
    row.language_name = dict(details.language_name)
    row.snapshot = dict(details.snapshot)
    row.view_url = details.view_url
    row.snapshot_hash = details.snapshot_hash
    row.feed_id = details.feed_id
    row.fetched_at = details.fetched_at
    row.detail_fetched_at = details.detail_fetched_at
    row.gone_at = details.gone_at


def _apply_book(row: BookRow, details: BookDetails) -> None:
    row.rights = details.rights.value
    row.licence = details.licence
    row.rights_basis = dict(details.rights_basis)
    row.rights_proof_file_id = details.rights_proof_file_id
    row.rights_checked_by = details.rights_checked_by
    row.rights_checked_at = details.rights_checked_at
    row.translators = list(details.translators)


def _apply_material(row: MaterialRow, details: MaterialDetails) -> None:
    row.uploader_id = details.uploader_id
    row.uploader_role = details.uploader_role.value
    row.uploader_name = details.uploader_name
    row.uploader_cohort = details.uploader_cohort
    row.licence = details.licence.value
    row.attested_at = details.attested_at
    row.approval = details.approval.value if details.approval else None
    row.submitted_at = details.submitted_at
    row.review_message = details.review_message
    row.scan = dict(details.scan)


def _apply_file(row: FileRow, item_file: ItemFile) -> None:
    row.format = item_file.format.value
    row.is_primary = item_file.is_primary
    row.pages = item_file.pages
    row.byte_size = item_file.byte_size
    row.readable = item_file.readable
    row.text_status = item_file.text_status.value
    row.toc = list(item_file.toc)
    row.sha256 = item_file.sha256


def _external_from(row: ExternalRow) -> ExternalDetails:
    return ExternalDetails(
        source=ExternalSource(row.source),
        external_id=row.external_id,
        category=row.category,
        access=ExternalAccess(row.access),
        view_url=row.view_url,
        snapshot_hash=row.snapshot_hash,
        fetched_at=row.fetched_at,
        type_name=dict(row.type_name),
        field_name=dict(row.field_name),
        language_name=dict(row.language_name),
        snapshot=dict(row.snapshot),
        feed_id=row.feed_id,
        detail_fetched_at=row.detail_fetched_at,
        gone_at=row.gone_at,
    )


def _book_from(row: BookRow) -> BookDetails:
    return BookDetails(
        rights=Rights(row.rights),
        licence=row.licence,
        rights_basis=dict(row.rights_basis),
        rights_proof_file_id=row.rights_proof_file_id,
        rights_checked_by=row.rights_checked_by,
        rights_checked_at=row.rights_checked_at,
        translators=list(row.translators),
    )


def _material_from(row: MaterialRow) -> MaterialDetails:
    return MaterialDetails(
        uploader_id=row.uploader_id,
        uploader_role=UploaderRole(row.uploader_role),
        uploader_name=row.uploader_name,
        licence=MaterialLicence(row.licence),
        uploader_cohort=row.uploader_cohort,
        attested_at=row.attested_at,
        approval=Approval(row.approval) if row.approval else None,
        submitted_at=row.submitted_at,
        review_message=row.review_message,
        scan=dict(row.scan),
    )


def _file_from(row: FileRow) -> ItemFile:
    return ItemFile(
        item_id=row.item_id,
        file_id=row.file_id,
        format=FileFormat(row.format),
        byte_size=row.byte_size,
        is_primary=row.is_primary,
        pages=row.pages,
        readable=row.readable,
        text_status=TextStatus(row.text_status),
        toc=list(row.toc),
        sha256=row.sha256.strip() if row.sha256 else None,
    )


def _item_from(row: ItemRow) -> Item:
    return Item(
        id=row.id,
        slug=row.slug,
        kind=ItemKind(row.kind),
        type=ItemType(row.type),
        title=row.title,
        language=ItemLanguage(row.language),
        status=ItemStatus(row.status),
        visibility=Visibility(row.visibility),
        created_at=row.created_at,
        updated_at=row.updated_at,
        title_alt=dict(row.title_alt),
        subtitle=row.subtitle,
        authors=list(row.authors),
        author_label=row.author_label,
        year_published=row.year_published,
        publisher=row.publisher,
        isbn=row.isbn,
        description=row.description,
        cover_file_id=row.cover_file_id,
        cover_url=row.cover_url,
        years_of_study=list(row.years_of_study),
        status_reason=row.status_reason,
        status_note=row.status_note,
        download_allowed=row.download_allowed,
        has_text=row.has_text,
        page_count=row.page_count,
        search_text=row.search_text,
        content_hash=row.content_hash.strip() if row.content_hash else None,
        owner_id=row.owner_id,
        reviewed_by=row.reviewed_by,
        reviewed_at=row.reviewed_at,
        published_at=row.published_at,
        supersedes_id=row.supersedes_id,
        open_reports=row.open_reports,
        created_by=row.created_by,
    )


# - - - Items - - -


class SqlItemRepository:
    """Stores items in schema `library`."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the unit of work's session."""
        self.session = session

    async def add(self, item: Item) -> None:
        """Insert the item with its details and files."""
        row = ItemRow(id=item.id, created_at=item.created_at)
        _apply_item(row, item)
        self.session.add(row)
        await self.session.flush()
        self._add_details(item)
        for item_file in item.files:
            await self.add_file(item_file)
        await self.session.flush()

    def _add_details(self, item: Item) -> None:
        if item.external is not None:
            ext = ExternalRow(item_id=item.id)
            _apply_external(ext, item.external)
            self.session.add(ext)
        if item.book is not None:
            book = BookRow(item_id=item.id)
            _apply_book(book, item.book)
            self.session.add(book)
        if item.material is not None:
            material = MaterialRow(item_id=item.id)
            _apply_material(material, item.material)
            self.session.add(material)

    async def get(self, item_id: UUID, *, lock: bool = False) -> Item | None:
        """The item or None; `lock` takes a row lock for a status change."""
        query = select(ItemRow).where(ItemRow.id == item_id)
        if lock:
            query = query.with_for_update()
        row = (await self.session.execute(query)).scalar_one_or_none()
        if row is None:
            return None
        return (await self._assemble([row]))[row.id]

    async def get_by_slug(self, slug: str) -> Item | None:
        """The item with this slug or None."""
        query = select(ItemRow).where(ItemRow.slug == slug)
        row = (await self.session.execute(query)).scalar_one_or_none()
        if row is None:
            return None
        return (await self._assemble([row]))[row.id]

    async def get_many(self, item_ids: Sequence[UUID]) -> dict[UUID, Item]:
        """The existing items (absent ids are missing from the result)."""
        if not item_ids:
            return {}
        query = select(ItemRow).where(ItemRow.id.in_(set(item_ids)))
        rows = list((await self.session.execute(query)).scalars())
        return await self._assemble(rows)

    async def get_by_external(
        self, source: ExternalSource, external_id: str
    ) -> Item | None:
        """The stored copy of an external record or None."""
        query = (
            select(ItemRow)
            .join(ExternalRow, ExternalRow.item_id == ItemRow.id)
            .where(
                ExternalRow.source == source.value,
                ExternalRow.external_id == external_id,
            )
        )
        row = (await self.session.execute(query)).scalar_one_or_none()
        if row is None:
            return None
        return (await self._assemble([row]))[row.id]

    async def _assemble(self, rows: Iterable[ItemRow]) -> dict[UUID, Item]:
        """Entities with the details of their kind and their files."""
        items = {row.id: _item_from(row) for row in rows}
        ids = list(items)
        if not ids:
            return items
        externals = await self.session.execute(
            select(ExternalRow).where(ExternalRow.item_id.in_(ids))
        )
        for ext in externals.scalars():
            items[ext.item_id].external = _external_from(ext)
        books = await self.session.execute(
            select(BookRow).where(BookRow.item_id.in_(ids))
        )
        for book in books.scalars():
            items[book.item_id].book = _book_from(book)
        materials = await self.session.execute(
            select(MaterialRow).where(MaterialRow.item_id.in_(ids))
        )
        for material in materials.scalars():
            items[material.item_id].material = _material_from(material)
        files = await self.session.execute(
            select(FileRow)
            .where(FileRow.item_id.in_(ids))
            .order_by(FileRow.is_primary.desc(), FileRow.file_id)
        )
        for file_row in files.scalars():
            items[file_row.item_id].files.append(_file_from(file_row))
        return items

    async def save(self, item: Item) -> None:
        """Update the item row and the details of its kind (files are separate)."""
        row = await self.session.get(ItemRow, item.id)
        if row is None:
            raise LookupError(f"item {item.id} is not stored")
        _apply_item(row, item)
        if item.external is not None:
            ext = await self.session.get(ExternalRow, item.id)
            if ext is None:
                ext = ExternalRow(item_id=item.id)
                self.session.add(ext)
            _apply_external(ext, item.external)
        if item.book is not None:
            book = await self.session.get(BookRow, item.id)
            if book is None:
                book = BookRow(item_id=item.id)
                self.session.add(book)
            _apply_book(book, item.book)
        if item.material is not None:
            material = await self.session.get(MaterialRow, item.id)
            if material is None:
                material = MaterialRow(item_id=item.id)
                self.session.add(material)
            _apply_material(material, item.material)
        await self.session.flush()

    # - - - Files - - -

    async def add_file(self, item_file: ItemFile) -> None:
        """Attach a file to the item."""
        row = FileRow(item_id=item_file.item_id, file_id=item_file.file_id)
        _apply_file(row, item_file)
        self.session.add(row)
        await self.session.flush()

    async def save_file(self, item_file: ItemFile) -> None:
        """Update a file row (text status, pages, toc, hash)."""
        row = await self.session.get(FileRow, (item_file.item_id, item_file.file_id))
        if row is None:
            raise LookupError(f"file {item_file.file_id} is not attached")
        _apply_file(row, item_file)
        await self.session.flush()

    async def remove_file(self, item_id: UUID, file_id: UUID) -> None:
        """Detach a file from the item."""
        await self.session.execute(
            delete(FileRow).where(
                FileRow.item_id == item_id, FileRow.file_id == file_id
            )
        )

    # - - - Tags - - -

    async def subject_links(
        self, item_ids: Sequence[UUID]
    ) -> dict[UUID, list[SubjectLink]]:
        """Subject tags of the items (items without tags are absent)."""
        result: dict[UUID, list[SubjectLink]] = {}
        if not item_ids:
            return result
        rows = await self.session.execute(
            select(SubjectRow)
            .where(SubjectRow.item_id.in_(set(item_ids)))
            .order_by(SubjectRow.subject_id, SubjectRow.year_of_study)
        )
        for row in rows.scalars():
            result.setdefault(row.item_id, []).append(
                SubjectLink(
                    subject_id=row.subject_id,
                    role=SubjectRole(row.role),
                    year_of_study=row.year_of_study or None,
                )
            )
        return result

    async def set_subject_links(
        self, item_id: UUID, links: Sequence[SubjectLink]
    ) -> None:
        """Replace the subject tags of the item."""
        await self.session.execute(
            delete(SubjectRow).where(SubjectRow.item_id == item_id)
        )
        seen: set[tuple[UUID, int]] = set()
        for link in links:
            key = (link.subject_id, link.year_of_study or ANY_YEAR)
            if key in seen:
                continue
            seen.add(key)
            self.session.add(
                SubjectRow(
                    item_id=item_id,
                    subject_id=link.subject_id,
                    year_of_study=key[1],
                    role=link.role.value,
                )
            )
        await self.session.flush()

    async def topic_links(
        self, item_ids: Sequence[UUID]
    ) -> dict[UUID, list[TopicLink]]:
        """Topic tags of the items (items without tags are absent)."""
        result: dict[UUID, list[TopicLink]] = {}
        if not item_ids:
            return result
        rows = await self.session.execute(
            select(TopicRow)
            .where(TopicRow.item_id.in_(set(item_ids)))
            .order_by(TopicRow.position, TopicRow.page_from)
        )
        for row in rows.scalars():
            result.setdefault(row.item_id, []).append(
                TopicLink(
                    topic_id=row.topic_id,
                    page_from=row.page_from or None,
                    page_to=row.page_to,
                    position=row.position,
                )
            )
        return result

    async def set_topic_links(self, item_id: UUID, links: Sequence[TopicLink]) -> None:
        """Replace the topic tags of the item."""
        await self.session.execute(delete(TopicRow).where(TopicRow.item_id == item_id))
        seen: set[tuple[UUID, int]] = set()
        for link in links:
            key = (link.topic_id, link.page_from or WHOLE_ITEM)
            if key in seen:
                continue
            seen.add(key)
            self.session.add(
                TopicRow(
                    item_id=item_id,
                    topic_id=key[0],
                    page_from=key[1],
                    page_to=link.page_to,
                    position=link.position,
                )
            )
        await self.session.flush()

    # - - - Duplicates - - -

    async def find_by_file_hash(
        self, sha256: str, *, exclude: UUID | None = None
    ) -> list[UUID]:
        """Ids of items with a file of this SHA-256."""
        query = select(FileRow.item_id).where(FileRow.sha256 == sha256).distinct()
        if exclude is not None:
            query = query.where(FileRow.item_id != exclude)
        return list((await self.session.execute(query)).scalars())

    async def find_by_content_hash(
        self, content_hash: str, *, exclude: UUID | None = None
    ) -> list[UUID]:
        """Ids of items whose extracted text has this hash."""
        query = select(ItemRow.id).where(ItemRow.content_hash == content_hash)
        if exclude is not None:
            query = query.where(ItemRow.id != exclude)
        return list((await self.session.execute(query)).scalars())

    # - - - Search and lists (catalogue area) - - -

    async def search(
        self, filters: ItemFilters, viewer: Viewer, *, limit: int, offset: int
    ) -> list[SearchHit]:
        """Items the viewer may see that match, best first; at most `limit` rows."""
        stmt = item_search.search_statement(filters, viewer, limit=limit, offset=offset)
        ids = list((await self.session.execute(stmt)).scalars())
        hits: dict[UUID, SearchHit] = {}
        if filters.query is not None:
            hits = await item_search.page_hits(self.session, filters.query, ids)
        return [hits.get(item_id) or SearchHit(item_id) for item_id in ids]

    async def subject_counts(self, viewer: Viewer) -> dict[UUID, int]:
        """Number of listed items per subject (published, not hidden, audience)."""
        rows = await self.session.execute(item_search.subject_counts_statement(viewer))
        return {subject_id: int(count) for subject_id, count in rows.all()}

    async def list_books(
        self,
        *,
        query: str | None,
        status: ItemStatus | None,
        limit: int,
        offset: int,
    ) -> list[UUID]:
        """Ids of books in any status for the librarian table, newest change first."""
        stmt = item_search.books_statement(
            query=query, status=status, limit=limit, offset=offset
        )
        return list((await self.session.execute(stmt)).scalars())

    async def sitemap_entries(self, *, limit: int) -> list[tuple[str, datetime]]:
        """Slug and last change of the public published books and materials."""
        rows = await self.session.execute(
            select(ItemRow.slug, ItemRow.updated_at)
            .where(
                ItemRow.kind.in_([ItemKind.BOOK.value, ItemKind.MATERIAL.value]),
                ItemRow.status == ItemStatus.PUBLISHED.value,
                ItemRow.visibility == Visibility.PUBLIC.value,
            )
            .order_by(ItemRow.updated_at.desc(), ItemRow.id)
            .limit(limit)
        )
        return [(slug, changed) for slug, changed in rows.all()]

    async def collection_ids(self, item_id: UUID) -> list[UUID]:
        """Collections the item is on."""
        rows = await self.session.execute(
            select(orm.CollectionItem.collection_id).where(
                orm.CollectionItem.item_id == item_id
            )
        )
        return list(rows.scalars())


# - - - History - - -


class SqlEventRepository:
    """Append-only history of items."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the unit of work's session."""
        self.session = session

    async def append(
        self,
        item_id: UUID,
        kind: EventKind,
        *,
        at: datetime,
        actor_id: UUID | None = None,
        data: dict[str, Any] | None = None,
    ) -> ItemEvent:
        """Add an event with the next sequence number of the item."""
        last = await self.session.scalar(
            select(func.coalesce(func.max(EventRow.seq), 0)).where(
                EventRow.item_id == item_id
            )
        )
        seq = int(last or 0) + 1
        self.session.add(
            EventRow(
                item_id=item_id,
                seq=seq,
                kind=kind.value,
                actor_id=actor_id,
                data=dict(data or {}),
                at=at,
            )
        )
        await self.session.flush()
        return ItemEvent(
            item_id=item_id,
            seq=seq,
            kind=kind,
            at=at,
            actor_id=actor_id,
            data=data or {},
        )

    async def history(self, item_id: UUID) -> list[ItemEvent]:
        """The events of the item, oldest first."""
        rows = await self.session.execute(
            select(EventRow).where(EventRow.item_id == item_id).order_by(EventRow.seq)
        )
        return [
            ItemEvent(
                item_id=row.item_id,
                seq=row.seq,
                kind=EventKind(row.kind),
                at=row.at,
                actor_id=row.actor_id,
                data=dict(row.data),
            )
            for row in rows.scalars()
        ]
