"""Port: storage of certificate entries and their files."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

from app.modules.certificates.domain.entry import CertificateEntry, EntryFile


@dataclass(frozen=True, slots=True)
class EntryFilter:
    """Which entries a staff query wants (``student_ids`` is the allowed set)."""

    student_ids: Sequence[UUID]
    type_id: UUID | None = None
    subject: str | None = None
    level: str | None = None
    custom: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    """Custom choice or text key -> any of these values."""
    ranges: Mapping[str, tuple[float | None, float | None]] = field(
        default_factory=dict
    )
    """Custom number key -> (min, max), either end open."""


class EntryRepository(Protocol):
    """Entries with their files."""

    async def add(self, entry: CertificateEntry) -> None:
        """Insert an entry (its files are added one by one)."""
        ...

    async def get(self, entry_id: UUID) -> CertificateEntry | None:
        """Return the entry with files or None."""
        ...

    async def save(self, entry: CertificateEntry) -> None:
        """Write the entry's fields (not its files)."""
        ...

    async def delete(self, entry_id: UUID) -> None:
        """Delete the entry and its file rows."""
        ...

    async def list_for_student(self, student_id: UUID) -> list[CertificateEntry]:
        """Return the student's entries with files, newest first."""
        ...

    async def find_by_serial(
        self, student_id: UUID, type_id: UUID, serial: str
    ) -> CertificateEntry | None:
        """Return the student's entry of this type with this serial."""
        ...

    async def count_for_type(self, type_id: UUID) -> int:
        """Return how many entries use the type."""
        ...

    async def add_file(self, file: EntryFile) -> None:
        """Attach a file."""
        ...

    async def remove_file(self, file_id: UUID) -> None:
        """Detach a file."""
        ...

    async def entry_of_file(self, file_id: UUID) -> CertificateEntry | None:
        """Return the entry the file is attached to."""
        ...

    async def query(
        self, flt: EntryFilter, *, limit: int | None, offset: int
    ) -> tuple[list[CertificateEntry], int]:
        """Return a page (limit None: all) of matching entries and the total."""
        ...

    async def entries_of_files(
        self, file_ids: Sequence[UUID]
    ) -> list[CertificateEntry]:
        """Return the entries that hold any of the files."""
        ...
