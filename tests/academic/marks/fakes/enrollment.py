"""Fake AcademicEnrollment, ScheduleQueries and LinksApi for the marks tests."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.shared.contracts.academic import StudentRef
from app.shared.contracts.emis import EmisSubject
from app.shared.contracts.links import ResourceRef


class FakeEnrollment:
    """Records enrollment calls; ensure_student returns a fixed StudentRef."""

    def __init__(self, ref: StudentRef) -> None:
        """Answer ensure_student with this reference."""
        self.ref = ref
        self.ensured: list[dict[str, Any]] = []
        self.left: list[tuple[UUID, str]] = []
        self.synced_subjects: list[tuple[UUID, Sequence[EmisSubject]]] = []

    async def ensure_student(self, **kwargs: Any) -> StudentRef:
        """Record the call."""
        self.ensured.append(kwargs)
        return self.ref

    async def find_imported_student(self, **kwargs: Any) -> UUID | None:
        """Not used by marks."""
        return None

    async def sync_subjects(
        self, *, group_id: UUID, subjects: Sequence[EmisSubject]
    ) -> None:
        """Record the call."""
        self.synced_subjects.append((group_id, subjects))

    async def mark_left(self, user_id: UUID, *, reason: str) -> None:
        """Record the call."""
        self.left.append((user_id, reason))

    async def enqueue_student_sync(self, user_id: UUID) -> None:
        """Not used by marks."""


class FakeSchedule:
    """ScheduleQueries.get_student only."""

    def __init__(self, known: set[UUID]) -> None:
        """Know these students."""
        self.known = known

    async def get_student(self, user_id: UUID) -> StudentRef | None:
        """Return a reference for a known student."""
        if user_id not in self.known:
            return None
        return StudentRef(
            user_id=user_id,
            group_id=UUID(int=1),
            group_name="2TN2",
            subgroup=None,
            status="active",
            synced_at=None,
        )


class FakeLinks:
    """LinksApi.resources_for_lessons from a table."""

    def __init__(self, by_lesson: dict[UUID, list[ResourceRef]] | None = None) -> None:
        """Answer from this table."""
        self.by_lesson = by_lesson or {}

    async def resources_for_lessons(
        self, lesson_ids: Sequence[UUID]
    ) -> dict[UUID, list[ResourceRef]]:
        """Return resources of the requested lessons."""
        return {i: self.by_lesson[i] for i in lesson_ids if i in self.by_lesson}
