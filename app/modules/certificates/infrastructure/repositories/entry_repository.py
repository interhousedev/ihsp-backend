"""SQL repository of certificate entries and their files."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.modules.certificates.domain.entry import (
    CertificateEntry,
    EntryFile,
    EntrySource,
)
from app.modules.certificates.infrastructure.orm.certificate_entry import (
    CertificateEntryFileRow as FileRow,
)
from app.modules.certificates.infrastructure.orm.certificate_entry import (
    CertificateEntryRow as Row,
)
from app.modules.certificates.ports.entry_repository import EntryFilter

from sqlalchemy import (
    ColumnElement,
    Float,
    Select,
    String,
    and_,
    case,
    cast,
    delete,
    func,
    or_,
    select,
)
from sqlalchemy.dialects.postgresql import array
from sqlalchemy.ext.asyncio import AsyncSession


def _file(row: FileRow) -> EntryFile:
    return EntryFile(row.file_id, row.entry_id, row.name, row.size, row.content_type)


def _entity(row: Row, files: Sequence[FileRow]) -> CertificateEntry:
    return CertificateEntry(
        id=row.id,
        student_id=row.student_id,
        type_id=row.type_id,
        created_at=row.created_at,
        source=EntrySource(row.source),
        issued_at=row.issued_at,
        expires_at=row.expires_at,
        files=[_file(f) for f in files],
        custom_values=dict(row.custom_values or {}),
    )


def _apply(row: Row, entry: CertificateEntry) -> None:
    row.student_id = entry.student_id
    row.type_id = entry.type_id
    row.source = entry.source.value
    row.issued_at = entry.issued_at
    row.expires_at = entry.expires_at
    row.custom_values = dict(entry.custom_values)


def _filtered(flt: EntryFilter) -> Select[tuple[Row]]:
    stmt = select(Row).where(Row.student_id.in_(list(flt.student_ids)))
    if flt.type_id is not None:
        stmt = stmt.where(Row.type_id == flt.type_id)
    if flt.level is not None:
        stmt = stmt.where(Row.custom_values["level"].astext == flt.level)
    if flt.subject:
        subject = Row.custom_values["subject"].astext
        stmt = stmt.where(subject.ilike(f"%{_escape(flt.subject)}%", escape="\\"))
    for key, wanted in flt.custom.items():
        stmt = stmt.where(_custom_in(key, wanted))
    for key, (low, high) in flt.ranges.items():
        stmt = stmt.where(_custom_between(key, low, high))
    return stmt


def _custom_in(key: str, wanted: tuple[str, ...]) -> Any:
    # A scalar (text, single choice) or a jsonb array (multi choice) may match.
    scalar = Row.custom_values[key].astext.in_(list(wanted))
    listed = Row.custom_values[key].has_any(array(list(wanted), type_=String))
    return or_(scalar, listed)


def _custom_between(key: str, low: float | None, high: float | None) -> Any:
    value = Row.custom_values[key]
    number = case(
        (func.jsonb_typeof(value) == "number", cast(value.astext, Float)),
        else_=None,
    )
    conditions: list[ColumnElement[bool]] = [number.is_not(None)]
    if low is not None:
        conditions.append(number >= low)
    if high is not None:
        conditions.append(number <= high)
    return and_(*conditions)


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class SqlEntryRepository:
    """Entries in `certificates.entries` with files in `entry_files`."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the unit of work's session."""
        self.session = session

    async def _with_files(self, rows: Sequence[Row]) -> list[CertificateEntry]:
        if not rows:
            return []
        stmt = (
            select(FileRow)
            .where(FileRow.entry_id.in_([r.id for r in rows]))
            .order_by(FileRow.created_at, FileRow.file_id)
        )
        grouped: dict[UUID, list[FileRow]] = {}
        for file_row in await self.session.scalars(stmt):
            grouped.setdefault(file_row.entry_id, []).append(file_row)
        return [_entity(row, grouped.get(row.id, [])) for row in rows]

    async def add(self, entry: CertificateEntry) -> None:
        """Insert an entry."""
        row = Row(id=entry.id)
        row.created_at = entry.created_at
        row.updated_at = entry.created_at
        _apply(row, entry)
        self.session.add(row)
        await self.session.flush()

    async def get(self, entry_id: UUID) -> CertificateEntry | None:
        """Return the entry with files or None."""
        row = await self.session.get(Row, entry_id)
        if row is None:
            return None
        return (await self._with_files([row]))[0]

    async def save(self, entry: CertificateEntry) -> None:
        """Write the entry's fields."""
        row = await self.session.get(Row, entry.id)
        if row is not None:
            _apply(row, entry)
            await self.session.flush()

    async def delete(self, entry_id: UUID) -> None:
        """Delete the entry (file rows go with it)."""
        await self.session.execute(delete(Row).where(Row.id == entry_id))

    async def list_for_student(self, student_id: UUID) -> list[CertificateEntry]:
        """Return the student's entries, newest first."""
        stmt = (
            select(Row)
            .where(Row.student_id == student_id)
            .order_by(Row.created_at.desc(), Row.id.desc())
        )
        return await self._with_files(list(await self.session.scalars(stmt)))

    async def find_by_serial(
        self, student_id: UUID, type_id: UUID, serial: str
    ) -> CertificateEntry | None:
        """Return the student's entry of this type with this serial."""
        stmt = select(Row).where(
            Row.student_id == student_id,
            Row.type_id == type_id,
            Row.custom_values["serial"].astext == serial,
        )
        row = await self.session.scalar(stmt)
        return None if row is None else (await self._with_files([row]))[0]

    async def count_for_type(self, type_id: UUID) -> int:
        """Return how many entries use the type."""
        stmt = select(func.count()).select_from(Row).where(Row.type_id == type_id)
        return int(await self.session.scalar(stmt) or 0)

    async def add_file(self, file: EntryFile) -> None:
        """Attach a file."""
        self.session.add(
            FileRow(
                file_id=file.id,
                entry_id=file.entry_id,
                name=file.name,
                size=file.size,
                content_type=file.content_type,
            )
        )
        await self.session.flush()

    async def remove_file(self, file_id: UUID) -> None:
        """Detach a file."""
        await self.session.execute(delete(FileRow).where(FileRow.file_id == file_id))

    async def entry_of_file(self, file_id: UUID) -> CertificateEntry | None:
        """Return the entry the file is attached to."""
        file_row = await self.session.get(FileRow, file_id)
        return None if file_row is None else await self.get(file_row.entry_id)

    async def query(
        self, flt: EntryFilter, *, limit: int | None, offset: int
    ) -> tuple[list[CertificateEntry], int]:
        """Return a page (limit None: all) of matching entries and the total."""
        if not flt.student_ids:
            return [], 0
        base = _filtered(flt)
        total = await self.session.scalar(
            select(func.count()).select_from(base.subquery())
        )
        stmt = base.order_by(Row.created_at.desc(), Row.id.desc()).offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)
        rows = list(await self.session.scalars(stmt))
        return await self._with_files(rows), int(total or 0)

    async def entries_of_files(
        self, file_ids: Sequence[UUID]
    ) -> list[CertificateEntry]:
        """Return the entries that hold any of the files."""
        if not file_ids:
            return []
        stmt = (
            select(Row)
            .join(FileRow, FileRow.entry_id == Row.id)
            .where(FileRow.file_id.in_(list(file_ids)))
            .distinct()
        )
        return await self._with_files(list(await self.session.scalars(stmt)))
