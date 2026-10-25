"""Temporary gradebook: lesson marks kept until the teacher enters them in EMIS."""

import datetime as dt
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

from app.modules.academic.domain.classwork.errors import (
    TemporaryMarkCommentInvalidError,
    TemporaryMarkValueInvalidError,
)

# The EMIS mark scale (``academic.marks.value BETWEEN 2 AND 5``).
MARK_SCALE: Final = (2, 3, 4, 5)
COMMENT_MAX: Final = 500


@dataclass(frozen=True, slots=True)
class TemporaryMark:
    """One student's temporary mark for one lesson."""

    id: UUID
    lesson_id: UUID
    student_id: UUID
    subject_id: UUID
    date: dt.date
    value: int
    comment: str | None
    author_id: UUID
    created_at: dt.datetime
    updated_at: dt.datetime


@dataclass(frozen=True, slots=True)
class TemporaryMarkView:
    """A temporary mark with the names to show it."""

    mark: TemporaryMark
    student_name: str
    group_id: UUID | None
    group_name: str
    subject_name: str
    lesson_period: int
    teacher_id: UUID | None
    teacher_name: str

    def to_json(self) -> dict[str, Any]:
        """Return the ``TemporaryMarkResponse`` fields."""
        mark = self.mark
        return {
            "id": str(mark.id),
            "lesson_id": str(mark.lesson_id),
            "lesson_date": mark.date.isoformat(),
            "lesson_period": self.lesson_period,
            "student_id": str(mark.student_id),
            "student_name": self.student_name,
            "group_id": None if self.group_id is None else str(self.group_id),
            "group_name": self.group_name,
            "subject_id": str(mark.subject_id),
            "subject_name": self.subject_name,
            "teacher_id": None if self.teacher_id is None else str(self.teacher_id),
            "teacher_name": self.teacher_name,
            "value": mark.value,
            "comment": mark.comment,
            "author_id": str(mark.author_id),
            "created_at": mark.created_at.isoformat(),
            "updated_at": mark.updated_at.isoformat(),
        }


def ensure_value(value: int) -> int:
    """Return the value when it is on the EMIS scale.

    Raises:
        TemporaryMarkValueInvalidError: not one of 2, 3, 4, 5.
    """
    if isinstance(value, bool) or value not in MARK_SCALE:
        raise TemporaryMarkValueInvalidError(
            params={"min": MARK_SCALE[0], "max": MARK_SCALE[-1]}
        )
    return value


def clean_comment(comment: str | None) -> str | None:
    """Strip the comment; blank becomes None.

    Raises:
        TemporaryMarkCommentInvalidError: longer than ``COMMENT_MAX``.
    """
    if comment is None:
        return None
    text = comment.strip()
    if not text:
        return None
    if len(text) > COMMENT_MAX:
        raise TemporaryMarkCommentInvalidError(params={"max": COMMENT_MAX})
    return text
