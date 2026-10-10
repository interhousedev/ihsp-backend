"""SQLAlchemy repository of file metadata (files.files)."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.files.domain.list_filters import escape_like
from app.modules.files.domain.status import FileStatus
from app.modules.files.domain.stored_file import StoredFile
from app.modules.files.infrastructure.orm.file import File
from app.shared.contracts.files import FilePurpose, FileScope

from sqlalchemy import (
    ColumnElement,
    and_,
    delete,
    distinct,
    func,
    literal_column,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession

_PURPOSE_KEY = "purpose"
_SIMPLE: ColumnElement[Any] = literal_column("'simple'::regconfig")
_INDEX_CHARS = 1_000_000
_HEADLINE_CHARS = 200_000
_HEADLINE_OPTIONS = (
    "MaxWords=35, MinWords=15, ShortWord=2, MaxFragments=2, "
    'FragmentDelimiter=" ... ", StartSel="**", StopSel="**"'
)
# Library files belong to the library: not My files, not the assistant's, not
# deleted with the account, and never cleaned up (FILE-6 is for students and mail).
_NOT_LIBRARY: ColumnElement[bool] = File.scope != FileScope.LIBRARY.value
_COUNTED = (
    FileStatus.PENDING.value,
    FileStatus.PROCESSING.value,
    FileStatus.READY.value,
)


def _to_entity(row: File) -> StoredFile:
    meta = dict(row.meta or {})
    purpose = FilePurpose(meta.pop(_PURPOSE_KEY, FilePurpose.LINK.value))
    return StoredFile(
        id=row.id,
        owner_id=row.owner_id,
        scope=FileScope(row.scope),
        purpose=purpose,
        key=row.key,
        name=row.name,
        content_type=row.content_type,
        byte_size=row.byte_size,
        checksum=row.checksum,
        status=FileStatus(row.status),
        created_at=row.created_at,
        updated_at=row.updated_at,
        reject_reason=row.reject_reason,
        metadata=meta,
        text_bytes=row.text_bytes,
        term_id=row.term_id,
        expires_at=row.expires_at,
        deleted_at=row.deleted_at,
    )


def _apply(row: File, file: StoredFile) -> None:
    row.owner_id = file.owner_id
    row.scope = file.scope.value
    row.key = file.key
    row.name = file.name
    row.content_type = file.content_type
    row.byte_size = file.byte_size
    row.checksum = file.checksum
    row.status = file.status.value
    row.reject_reason = file.reject_reason
    row.meta = {**file.metadata, _PURPOSE_KEY: file.purpose.value}
    row.text_bytes = file.text_bytes
    row.term_id = file.term_id
    row.expires_at = file.expires_at
    row.deleted_at = file.deleted_at
    row.created_at = file.created_at
    row.updated_at = file.updated_at


class SqlFileRepository:
    """FileRepository over one AsyncSession owned by the unit of work."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the unit of work's session."""
        self._session = session

    async def lock_owner(self, owner_id: UUID) -> None:
        """Serialise quota checks of one owner until the transaction ends."""
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:owner))"),
            {"owner": str(owner_id)},
        )

    async def used_bytes(
        self, owner_id: UUID, scope: FileScope, term_id: UUID | None
    ) -> int:
        """Sum counted bytes: this term for students, everything for staff."""
        stmt = select(func.coalesce(func.sum(File.byte_size), 0)).where(
            File.owner_id == owner_id,
            File.scope == scope.value,
            File.status.in_(_COUNTED),
        )
        if scope == FileScope.STUDENT:
            stmt = stmt.where(
                File.term_id.is_(None) if term_id is None else File.term_id == term_id
            )
        return int((await self._session.execute(stmt)).scalar_one())

    async def add(self, file: StoredFile) -> None:
        """Insert a new row."""
        row = File(id=file.id)
        _apply(row, file)
        self._session.add(row)
        await self._session.flush()

    async def save(self, file: StoredFile) -> None:
        """Update an existing row."""
        row = await self._session.get(File, file.id)
        if row is None:
            raise LookupError(f"file {file.id} does not exist")
        _apply(row, file)
        await self._session.flush()

    async def get(self, file_id: UUID) -> StoredFile | None:
        """Return the file or None."""
        row = await self._session.get(File, file_id)
        return None if row is None else _to_entity(row)

    async def get_many(self, file_ids: Sequence[UUID]) -> list[StoredFile]:
        """Return the existing files among the ids."""
        if not file_ids:
            return []
        rows = await self._session.scalars(select(File).where(File.id.in_(file_ids)))
        return [_to_entity(row) for row in rows]

    async def list_for_owner(
        self,
        owner_id: UUID,
        *,
        purpose: FilePurpose | None,
        after: tuple[datetime, UUID] | None,
        limit: int,
        name_query: str | None = None,
        content_types: Sequence[str] | None = None,
        oldest_first: bool = False,
        offset: int = 0,
    ) -> list[StoredFile]:
        """List the owner's files, newest first; pending and deleted are hidden."""
        stmt = select(File).where(
            File.owner_id == owner_id,
            _NOT_LIBRARY,
            File.status.not_in((FileStatus.PENDING.value, FileStatus.DELETED.value)),
        )
        if purpose is not None:
            stmt = stmt.where(File.meta.op("->>")(_PURPOSE_KEY) == purpose.value)
        if after is not None:
            created, last_id = after
            stmt = stmt.where(
                or_(
                    File.created_at < created,
                    and_(File.created_at == created, File.id < last_id),
                )
            )
        if name_query:
            stmt = stmt.where(
                File.name.ilike(f"%{escape_like(name_query)}%", escape="\\")
            )
        if content_types is not None:
            stmt = stmt.where(File.content_type.in_(tuple(content_types)))
        if oldest_first:
            stmt = stmt.order_by(File.created_at.asc(), File.id.asc())
        else:
            stmt = stmt.order_by(File.created_at.desc(), File.id.desc())
        stmt = stmt.offset(offset).limit(limit)
        return [_to_entity(row) for row in await self._session.scalars(stmt)]

    async def list_ready(self, owner_id: UUID, limit: int) -> list[StoredFile]:
        """List the owner's ready files, newest first."""
        stmt = (
            select(File)
            .where(
                File.owner_id == owner_id,
                _NOT_LIBRARY,
                File.status == FileStatus.READY.value,
            )
            .order_by(File.created_at.desc(), File.id.desc())
            .limit(limit)
        )
        return [_to_entity(row) for row in await self._session.scalars(stmt)]

    async def list_for_owner_all(self, owner_id: UUID, limit: int) -> list[StoredFile]:
        """List every file of the owner that is not deleted."""
        stmt = (
            select(File)
            .where(
                File.owner_id == owner_id,
                _NOT_LIBRARY,
                File.status != FileStatus.DELETED.value,
            )
            .order_by(File.created_at, File.id)
            .limit(limit)
        )
        return [_to_entity(row) for row in await self._session.scalars(stmt)]

    async def set_text(self, file_id: UUID, text_bytes: int, content: str) -> None:
        """Store the text size and the search vector (first million characters)."""
        vector = func.to_tsvector(_SIMPLE, func.left(content, _INDEX_CHARS))
        await self._session.execute(
            update(File)
            .where(File.id == file_id)
            .values(text_bytes=text_bytes, search_vector=vector)
        )

    async def search(self, owner_id: UUID, query: str, limit: int) -> list[StoredFile]:
        """Return ready files whose text matches all words of the query."""
        tsquery = func.plainto_tsquery(_SIMPLE, query)
        stmt = (
            select(File)
            .where(
                File.owner_id == owner_id,
                _NOT_LIBRARY,
                File.status == FileStatus.READY.value,
                File.search_vector.op("@@")(tsquery),
            )
            .order_by(func.ts_rank(File.search_vector, tsquery).desc(), File.id)
            .limit(limit)
        )
        return [_to_entity(row) for row in await self._session.scalars(stmt)]

    async def headline(self, document: str, query: str) -> str:
        """Return a short fragment of the document around the query words."""
        stmt = select(
            func.ts_headline(
                _SIMPLE,
                document[:_HEADLINE_CHARS],
                func.plainto_tsquery(_SIMPLE, query),
                _HEADLINE_OPTIONS,
            )
        )
        return str((await self._session.execute(stmt)).scalar_one())

    async def student_term_ids(self) -> list[UUID]:
        """Terms that still have live student files."""
        stmt = select(distinct(File.term_id)).where(
            File.scope == FileScope.STUDENT.value,
            File.term_id.is_not(None),
            File.status != FileStatus.DELETED.value,
        )
        return [term_id for term_id in await self._session.scalars(stmt) if term_id]

    async def list_expired(
        self, *, expired_term_ids: Sequence[UUID], now: datetime, limit: int
    ) -> list[StoredFile]:
        """Files of expired terms and files past their own expires_at."""
        due: ColumnElement[bool] = and_(
            File.expires_at.is_not(None), File.expires_at < now
        )
        if expired_term_ids:
            term_due = and_(
                File.scope == FileScope.STUDENT.value,
                File.term_id.in_(expired_term_ids),
            )
            due = or_(due, term_due)
        stmt = (
            select(File)
            .where(File.status != FileStatus.DELETED.value, _NOT_LIBRARY, due)
            .order_by(File.created_at, File.id)
            .limit(limit)
        )
        return [_to_entity(row) for row in await self._session.scalars(stmt)]

    async def term_owner_counts(self, term_id: UUID) -> list[tuple[UUID, int]]:
        """Owners with live student files of the term, and how many."""
        stmt = (
            select(File.owner_id, func.count())
            .where(
                File.scope == FileScope.STUDENT.value,
                File.term_id == term_id,
                File.status.in_((FileStatus.PROCESSING.value, FileStatus.READY.value)),
            )
            .group_by(File.owner_id)
            .order_by(File.owner_id)
        )
        return [
            (owner, int(count)) for owner, count in await self._session.execute(stmt)
        ]

    async def list_stale_uploads(
        self, older_than: datetime, limit: int
    ) -> list[StoredFile]:
        """Pending uploads and rejected files older than the moment."""
        stmt = (
            select(File)
            .where(
                or_(
                    and_(
                        File.status == FileStatus.PENDING.value,
                        File.created_at < older_than,
                    ),
                    and_(
                        File.status == FileStatus.REJECTED.value,
                        File.updated_at < older_than,
                    ),
                )
            )
            .order_by(File.created_at, File.id)
            .limit(limit)
        )
        return [_to_entity(row) for row in await self._session.scalars(stmt)]

    async def list_stale_processing(
        self, older_than: datetime, limit: int
    ) -> list[StoredFile]:
        """Files in processing since before the moment."""
        stmt = (
            select(File)
            .where(
                File.status == FileStatus.PROCESSING.value,
                File.updated_at < older_than,
            )
            .order_by(File.updated_at, File.id)
            .limit(limit)
        )
        return [_to_entity(row) for row in await self._session.scalars(stmt)]

    async def mark_deleted(self, file_ids: Sequence[UUID], now: datetime) -> None:
        """Soft-delete rows in bulk and clear their search vectors."""
        if not file_ids:
            return
        await self._session.execute(
            update(File)
            .where(File.id.in_(file_ids))
            .values(
                status=FileStatus.DELETED.value,
                deleted_at=now,
                updated_at=now,
                search_vector=None,
                text_bytes=None,
            )
        )

    async def delete_rows(self, file_ids: Sequence[UUID]) -> None:
        """Remove rows entirely."""
        if not file_ids:
            return
        await self._session.execute(delete(File).where(File.id.in_(file_ids)))
