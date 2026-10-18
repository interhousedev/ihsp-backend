"""In-memory unit of work of the certificates module (copies in and out)."""

import copy
from collections.abc import Callable, Sequence
from types import TracebackType
from typing import Self
from uuid import UUID

from app.modules.certificates.domain.certificate_type import CertificateType
from app.modules.certificates.domain.entry import CertificateEntry, EntryFile
from app.modules.certificates.ports.entry_repository import EntryFilter


class FakeCertificatesStore:
    """The "database": types and entries shared by every unit of work."""

    def __init__(self) -> None:
        """Start empty."""
        self.types: dict[UUID, CertificateType] = {}
        self.entries: dict[UUID, CertificateEntry] = {}
        self.commits = 0


class FakeTypeRepository:
    """Types of a FakeCertificatesStore."""

    def __init__(self, store: FakeCertificatesStore) -> None:
        """Bind to the store."""
        self.store = store

    async def list_all(self) -> list[CertificateType]:
        """Return all types by position."""
        rows = sorted(self.store.types.values(), key=lambda t: (t.position, t.code))
        return copy.deepcopy(rows)

    async def get(self, type_id: UUID) -> CertificateType | None:
        """Return a copy of the type."""
        found = self.store.types.get(type_id)
        return copy.deepcopy(found) if found else None

    async def get_by_code(self, code: str) -> CertificateType | None:
        """Return the type with this code."""
        for kind in self.store.types.values():
            if kind.code == code:
                return copy.deepcopy(kind)
        return None

    async def add(self, kind: CertificateType) -> None:
        """Insert a type."""
        self.store.types[kind.id] = copy.deepcopy(kind)

    async def save(self, kind: CertificateType) -> None:
        """Store the type's fields."""
        self.store.types[kind.id] = copy.deepcopy(kind)

    async def delete(self, type_id: UUID) -> None:
        """Delete the type."""
        self.store.types.pop(type_id, None)

    async def next_position(self) -> int:
        """Position after the last type."""
        return max((t.position for t in self.store.types.values()), default=-1) + 1


class FakeEntryRepository:
    """Entries of a FakeCertificatesStore."""

    def __init__(self, store: FakeCertificatesStore) -> None:
        """Bind to the store."""
        self.store = store

    async def add(self, entry: CertificateEntry) -> None:
        """Insert an entry."""
        self.store.entries[entry.id] = copy.deepcopy(entry)

    async def get(self, entry_id: UUID) -> CertificateEntry | None:
        """Return a copy of the entry."""
        found = self.store.entries.get(entry_id)
        return copy.deepcopy(found) if found else None

    async def save(self, entry: CertificateEntry) -> None:
        """Store the entry's fields (the files stay as stored)."""
        kept = self.store.entries[entry.id].files
        saved = copy.deepcopy(entry)
        saved.files = kept
        self.store.entries[entry.id] = saved

    async def delete(self, entry_id: UUID) -> None:
        """Delete the entry with its files."""
        self.store.entries.pop(entry_id, None)

    async def list_for_student(self, student_id: UUID) -> list[CertificateEntry]:
        """Newest first."""
        rows = [e for e in self.store.entries.values() if e.student_id == student_id]
        rows.sort(key=lambda e: (e.created_at, e.id), reverse=True)
        return copy.deepcopy(rows)

    async def find_by_serial(
        self, student_id: UUID, type_id: UUID, serial: str
    ) -> CertificateEntry | None:
        """The student's entry with this type and serial."""
        for entry in self.store.entries.values():
            if (entry.student_id, entry.type_id, entry.serial) == (
                student_id,
                type_id,
                serial,
            ):
                return copy.deepcopy(entry)
        return None

    async def count_for_type(self, type_id: UUID) -> int:
        """How many entries use the type."""
        return sum(1 for e in self.store.entries.values() if e.type_id == type_id)

    async def add_file(self, file: EntryFile) -> None:
        """Attach a file."""
        self.store.entries[file.entry_id].files.append(file)

    async def remove_file(self, file_id: UUID) -> None:
        """Detach a file."""
        for entry in self.store.entries.values():
            entry.files = [f for f in entry.files if f.id != file_id]

    async def entry_of_file(self, file_id: UUID) -> CertificateEntry | None:
        """The entry holding the file."""
        for entry in self.store.entries.values():
            if any(f.id == file_id for f in entry.files):
                return copy.deepcopy(entry)
        return None

    async def query(
        self, flt: EntryFilter, *, limit: int | None, offset: int
    ) -> tuple[list[CertificateEntry], int]:
        """Matching entries, newest first, and the total."""
        rows = [
            e
            for e in self.store.entries.values()
            if e.student_id in set(flt.student_ids)
            and (flt.type_id is None or e.type_id == flt.type_id)
            and (flt.level is None or e.level == flt.level)
            and (
                not flt.subject
                or flt.subject.casefold() in (e.subject or "").casefold()
            )
            and _custom_matches(e.custom_values, flt)
        ]
        rows.sort(key=lambda e: (e.created_at, e.id), reverse=True)
        page = rows[offset:] if limit is None else rows[offset : offset + limit]
        return copy.deepcopy(page), len(rows)

    async def entries_of_files(
        self, file_ids: Sequence[UUID]
    ) -> list[CertificateEntry]:
        """Entries that hold any of the files."""
        wanted = set(file_ids)
        found = [
            e
            for e in self.store.entries.values()
            if any(f.id in wanted for f in e.files)
        ]
        return copy.deepcopy(found)


def _custom_matches(values: dict[str, object], flt: EntryFilter) -> bool:
    """Same rule as the SQL filter: a scalar or a list may contain a wanted value."""
    for key, wanted in flt.custom.items():
        value = values.get(key)
        held = value if isinstance(value, list) else [value]
        if not any(v in wanted for v in held):
            return False
    for key, (low, high) in flt.ranges.items():
        number = values.get(key)
        if isinstance(number, bool) or not isinstance(number, int | float):
            return False
        if (low is not None and number < low) or (high is not None and number > high):
            return False
    return True


class FakeCertificatesUnitOfWork:
    """Same interface as the SQL unit of work."""

    def __init__(self, store: FakeCertificatesStore) -> None:
        """Bind to the store."""
        self.store = store
        self.types = FakeTypeRepository(store)
        self.entries = FakeEntryRepository(store)

    async def __aenter__(self) -> Self:
        """Nothing to open."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Nothing to roll back (writes are immediate)."""

    async def commit(self) -> None:
        """Count the commit."""
        self.store.commits += 1


def fake_uow_factory(
    store: FakeCertificatesStore,
) -> Callable[[], FakeCertificatesUnitOfWork]:
    """Return a factory that makes a fresh unit of work per use."""
    return lambda: FakeCertificatesUnitOfWork(store)
