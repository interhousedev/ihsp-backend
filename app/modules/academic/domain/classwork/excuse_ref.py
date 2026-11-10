"""The official excuse that locked an attendance entry, kept in its comment.

One rule decides whether a student is excused for a lesson: the student is absent
and an excuse mark is saved for the absence or an approved excuse covers the
lesson. ``effective_excuses`` is that rule; every reader goes through it.
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

PREFIX = "excuse:"
TEACHER_ORIGIN = "teacher"


@dataclass(frozen=True, slots=True)
class ExcuseRef:
    """Which excuse covers an absence: id, template code and who started it.

    An absence excused by hand by a teacher has no excuse record: ``id`` is
    ``None``, the code is empty and the origin is ``teacher``.
    """

    id: UUID | None
    template_code: str
    origin: str

    def comment(self) -> str:
        """Return the attendance comment that records the excuse."""
        return f"{PREFIX}{self.id}:{self.template_code}:{self.origin}"

    def as_dict(self) -> dict[str, str | None]:
        """Return the DTO shape ``{id, template_code, origin}``."""
        return {
            "id": None if self.id is None else str(self.id),
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


def excuse_of_mark(mark: Mapping[str, Any] | None) -> ExcuseRef | None:
    """Return the official excuse recorded in one ``attendance_excused`` mark."""
    return parse_excuse_comment(mark.get("comment") if mark else None)


def effective_excuses(
    absent: Collection[UUID] | None,
    marks: Mapping[str, Mapping[str, Any]] | None,
    covered: Mapping[UUID, ExcuseRef],
) -> dict[UUID, ExcuseRef]:
    """Return the excuse of every excused absent student.

    A student is excused iff absent and (covered by an approved excuse or has an
    excuse mark). An official excuse wins over a teacher's own mark.
    """
    result: dict[UUID, ExcuseRef] = {}
    for student_id in absent or ():
        mark = (marks or {}).get(str(student_id))
        ref = excuse_of_mark(mark) or covered.get(student_id)
        if ref is None and mark is not None:
            ref = ExcuseRef(None, "", TEACHER_ORIGIN)
        if ref is not None:
            result[student_id] = ref
    return result
