"""Repository and read ports of assessments."""

import datetime as dt
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.modules.academic.domain.assessments.periods import TermControls
from app.modules.academic.domain.assessments.records import (
    Assessment,
    AssessmentKind,
    AssessmentSource,
    AssessmentStatus,
    NewAssessment,
)
from app.modules.academic.domain.marks.read_models import SubjectInfo

VISIBLE: tuple[AssessmentStatus, ...] = ("planned", "tentative")
ANY_STATUS: tuple[AssessmentStatus, ...] = ("planned", "tentative", "cancelled")
MAX_ROWS = 500


@dataclass(frozen=True, slots=True)
class AssessmentQuery:
    """Filters of an assessment listing; ``audience`` keeps controls that overlap it."""

    since: dt.date | None = None
    until: dt.date | None = None
    subject_id: UUID | None = None
    group_id: UUID | None = None
    audience: Sequence[str] | None = None
    kind: AssessmentKind | None = None
    source: AssessmentSource | None = None
    statuses: Sequence[AssessmentStatus] = VISIBLE
    limit: int = MAX_ROWS


@dataclass(frozen=True, slots=True)
class StudentAudience:
    """The group and subgroup of a student."""

    user_id: UUID
    group_id: UUID
    group_name: str
    subgroup: int | None


class AssessmentRepository(Protocol):
    """Stored assessments."""

    async def add(self, new: NewAssessment) -> Assessment:
        """Insert a control and return it."""
        ...

    async def get(self, assessment_id: UUID) -> Assessment | None:
        """Return a control by id, whatever its status."""
        ...

    async def save(self, assessment: Assessment) -> Assessment:
        """Write the editable fields of a control and return it."""
        ...

    async def find(self, query: AssessmentQuery) -> list[Assessment]:
        """Return controls by date and period of the query, oldest first."""
        ...


class AssessmentReader(Protocol):
    """Facts from other academic tables that assessments depend on."""

    async def student(self, user_id: UUID) -> StudentAudience | None:
        """Return the student's group and subgroup, or None."""
        ...

    async def head_student_of(self, group_id: UUID) -> UUID | None:
        """Return the head student of a group, or None."""
        ...

    async def subjects(self, subject_ids: Collection[UUID]) -> dict[UUID, SubjectInfo]:
        """Return subjects by id."""
        ...

    async def group_names(self, group_ids: Collection[UUID]) -> dict[UUID, str]:
        """Return the names of the groups that exist."""
        ...

    async def taught_groups(
        self, teacher_id: UUID, today: dt.date
    ) -> dict[UUID, set[UUID]]:
        """Return the groups a teacher teaches, per subject (timetable and lessons)."""
        ...

    async def lesson_subject(self, lesson_id: UUID) -> UUID | None:
        """Return the subject of a lesson, or None when there is no such lesson."""
        ...

    async def user_ids_for_audience(self, keys: Sequence[str]) -> list[UUID]:
        """Return the active students who belong to the audience."""
        ...

    async def terms(self) -> list[TermControls]:
        """Return every term with its control weeks, oldest first."""
        ...

    async def curriculum(self, group_id: UUID) -> tuple[UUID, ...]:
        """Return the subjects of a group's curriculum."""
        ...

    async def curricula(self) -> dict[UUID, tuple[UUID, ...]]:
        """Return the curriculum subjects of every active group that has any."""
        ...

    async def active_group_ids(self) -> list[UUID]:
        """Return the ids of the active groups (those whose controls are suggested)."""
        ...
