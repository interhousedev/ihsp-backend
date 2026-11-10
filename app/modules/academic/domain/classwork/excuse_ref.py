"""The official excuse that locked an attendance entry, kept in its comment."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

PREFIX = "excuse:"


@dataclass(frozen=True, slots=True)
class ExcuseRef:
    """Which excuse covers an absence: id, template code and who started it."""

    id: UUID
    template_code: str
    origin: str

    def comment(self) -> str:
        """Return the attendance comment that records the excuse."""
        return f"{PREFIX}{self.id}:{self.template_code}:{self.origin}"

    def as_dict(self) -> dict[str, str]:
        """Return the DTO shape ``{id, template_code, origin}``."""
        return {
            "id": str(self.id),
            "template_code": self.template_code,
            "origin": self.origin,
        }


def parse_excuse_comment(comment: str | None) -> ExcuseRef | None:
    """Parse ``excuse:<id>:<code>:<origin>``; any other comment gives ``None``."""
    if not comment or not comment.startswith(PREFIX):
        return None
    parts = comment[len(PREFIX) :].split(":")
    if len(parts) != 3:
        return None
    try:
        return ExcuseRef(UUID(parts[0]), parts[1], parts[2])
    except ValueError:
        return None


def excuse_of_mark(mark: Mapping[str, Any] | None) -> dict[str, str] | None:
    """Return the DTO ``excuse`` of one ``attendance_excused`` mark, if official."""
    ref = parse_excuse_comment(mark.get("comment") if mark else None)
    return ref.as_dict() if ref else None
