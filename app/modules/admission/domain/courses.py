"""Courses the student shows on the profile, merged from several sources."""

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal
from uuid import UUID

CourseSource = Literal["academic", "lms", "manual"]
SOURCE_ORDER: dict[str, int] = {"academic": 0, "lms": 1, "manual": 2}


@dataclass(frozen=True, slots=True)
class Course:
    """One course row; `id` is None for a source course not stored yet."""

    student_id: UUID
    source: CourseSource
    source_ref: str | None
    title: str
    provider: str | None = None
    level: str | None = None
    year: int | None = None
    grade: str | None = None
    included: bool = True
    id: UUID | None = None
    created_at: datetime | None = None

    @property
    def key(self) -> tuple[str, str]:
        """Identity across sources: manual rows by id, others by source ref."""
        if self.source == "manual" or self.source_ref is None:
            return (self.source, str(self.id))
        return (self.source, self.source_ref)


def merge(live: Iterable[Course], stored: Iterable[Course]) -> list[Course]:
    """Merge live source courses with stored rows.

    A stored row wins for its `included` flag and id; a live course refreshes the
    title and grade (the source is the truth). Stored academic or LMS rows whose
    source no longer lists them stay (an LMS snapshot survives unenrolment).
    """
    by_key: dict[tuple[str, str], Course] = {}
    for row in stored:
        by_key[row.key] = row
    for course in live:
        prior = by_key.get(course.key)
        if prior is None:
            by_key[course.key] = course
        else:
            by_key[course.key] = replace(
                prior, title=course.title, grade=course.grade or prior.grade
            )
    return sorted(
        by_key.values(),
        key=lambda c: (SOURCE_ORDER[c.source], -(c.year or 0), c.title.casefold()),
    )
