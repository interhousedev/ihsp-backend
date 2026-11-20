"""A student's platform certificates as admission reads them."""

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class StudentCertificate:
    """One certificate entry joined with its type."""

    entry_id: UUID
    type_code: str
    names: dict[str, str]
    standard: bool
    category: str | None
    issued_at: dt.date | None
    expires_at: dt.date | None
    values: dict[str, Any] = field(default_factory=dict)
    """The student's custom values by field key (level, score, subject ...)."""

    def name(self, locale: str) -> str:
        """The type name in the locale, else English, else the code."""
        return self.names.get(locale) or self.names.get("en") or self.type_code


class CertificateDirectory(Protocol):
    """Read the certificate entries of a student."""

    async def for_student(self, student_id: UUID) -> list[StudentCertificate]:
        """Return the student's entries, newest first."""
        ...
