"""A certificate of a student and its files."""

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class EntrySource(StrEnum):
    """Where an entry came from."""

    MANUAL = "manual"
    EMIS = "emis"


@dataclass(frozen=True, slots=True)
class EntryFile:
    """A file attached to an entry (``id`` is the file id in the files module)."""

    id: UUID
    entry_id: UUID
    name: str
    size: int
    content_type: str


@dataclass(slots=True)
class CertificateEntry:
    """One certificate of one student."""

    id: UUID
    student_id: UUID
    type_id: UUID
    created_at: datetime
    source: EntrySource = EntrySource.MANUAL
    issued_at: date | None = None
    expires_at: date | None = None
    files: list[EntryFile] = field(default_factory=list)
    custom_values: dict[str, Any] = field(default_factory=dict)
    """Values by the type's custom field keys (level, score, serial, ...)."""
