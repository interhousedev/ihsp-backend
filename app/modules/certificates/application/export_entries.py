"""Export certificate files as a streamed ZIP archive."""

import zipfile
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import IO, cast
from uuid import UUID

from app.modules.certificates.application.list_staff_entries import repo_filter
from app.modules.certificates.application.staff_scope import StaffFilters, StaffScope
from app.modules.certificates.domain.errors import (
    CertificateFileNotFoundError,
    NotCuratorError,
)
from app.modules.certificates.domain.export_names import NameDeduper, archive_name
from app.modules.certificates.ports.student_directory import StudentInfo
from app.modules.certificates.ports.unit_of_work import UowFactory
from app.shared.actor import Actor, Role
from app.shared.contracts.files import FilesApi

CHUNK = 64 * 1024


@dataclass(frozen=True, slots=True)
class ExportItem:
    """A stored file and its name inside the archive."""

    file_id: UUID
    name: str


class _Sink:
    """Write-only stream that collects bytes until the caller drains them."""

    def __init__(self) -> None:
        self._chunks: list[bytes] = []
        self._written = 0

    def write(self, data: bytes) -> int:
        """Collect bytes."""
        self._chunks.append(bytes(data))
        self._written += len(data)
        return len(data)

    def flush(self) -> None:
        """Nothing to flush."""

    def tell(self) -> int:
        """Bytes written so far (zipfile then writes data descriptors)."""
        return self._written

    def drain(self) -> bytes:
        """Return what was collected and forget it."""
        data = b"".join(self._chunks)
        self._chunks = []
        return data


class ExportEntries:
    """Plan an export (access is checked here), then stream the archive."""

    def __init__(
        self, *, uow_factory: UowFactory, scope: StaffScope, files: FilesApi
    ) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._scope = scope
        self._files = files

    async def plan(
        self,
        actor: Actor,
        *,
        file_ids: Sequence[UUID] | None,
        filters: StaffFilters | None,
    ) -> list[ExportItem]:
        """Name every file to export; raises before anything is streamed."""
        students = await self._scope.students(actor, StaffFilters())
        by_id = {s.id: s for s in students}
        if file_ids:
            items = await self._by_files(actor, file_ids, by_id)
        else:
            flt = filters or StaffFilters()
            scoped = await self._scope.students(actor, flt)
            items = await self._by_filters(scoped, flt)
        if not items:
            raise CertificateFileNotFoundError()
        return items

    async def stream(self, items: Sequence[ExportItem]) -> AsyncIterator[bytes]:
        """Yield the ZIP archive, holding one file in memory at a time."""
        sink = _Sink()
        # The sink has no seek(): zipfile then writes data descriptors (streaming).
        target = cast(IO[bytes], sink)
        archive = zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED)
        for item in items:
            data = await self._files.read_bytes(item.file_id)
            archive.writestr(item.name, data)
            chunk = sink.drain()
            for start in range(0, len(chunk), CHUNK):
                yield chunk[start : start + CHUNK]
        archive.close()
        yield sink.drain()

    async def _by_files(
        self, actor: Actor, file_ids: Sequence[UUID], by_id: dict[UUID, StudentInfo]
    ) -> list[ExportItem]:
        wanted = set(file_ids)
        async with self._uow_factory() as uow:
            entries = await uow.entries.entries_of_files(list(wanted))
        namer = NameDeduper()
        items: list[ExportItem] = []
        for entry in entries:
            student = by_id.get(entry.student_id)
            if student is None:
                if actor.has(Role.ADMIN):  # the student left the lyceum
                    continue
                raise NotCuratorError()
            for file in entry.files:
                if file.id in wanted:
                    items.append(_item(namer, student, file.id, file.name))
        return items

    async def _by_filters(
        self, students: list[StudentInfo], flt: StaffFilters
    ) -> list[ExportItem]:
        by_id = {s.id: s for s in students}
        async with self._uow_factory() as uow:
            rows, _ = await uow.entries.query(
                repo_filter(students, flt), limit=None, offset=0
            )
        namer = NameDeduper()
        return [
            _item(namer, by_id[row.student_id], file.id, file.name)
            for row in rows
            for file in row.files
        ]


def _item(
    namer: NameDeduper, student: StudentInfo, file_id: UUID, filename: str
) -> ExportItem:
    name = archive_name(student.group_name, student.name, filename)
    return ExportItem(file_id, namer.unique(name))
