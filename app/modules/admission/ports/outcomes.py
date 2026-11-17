"""Port of the outcome reports and the nudge queries."""

from collections.abc import Collection
from typing import Protocol
from uuid import UUID

from app.modules.admission.domain.outcomes import NudgeTarget, Outcome


class OutcomeRepository(Protocol):
    """Stored self-reported outcomes."""

    async def list_for(self, student_id: UUID) -> list[Outcome]:
        """The student's reports, newest cycle first."""
        ...

    async def get(self, outcome_id: UUID) -> Outcome | None:
        """One report."""
        ...

    async def find(
        self, student_id: UUID, institution_id: UUID, cycle: int
    ) -> Outcome | None:
        """The report of a cycle at an institution."""
        ...

    async def add(self, outcome: Outcome) -> Outcome:
        """Insert; a second report of the same cycle raises a conflict."""
        ...

    async def save(self, outcome: Outcome, *, expected_lock: int) -> Outcome:
        """Update; a stale lock raises a conflict."""
        ...

    async def delete(self, outcome_id: UUID) -> None:
        """Remove a report."""
        ...

    async def all(
        self, *, institution_id: UUID | None = None, cycle: int | None = None
    ) -> list[Outcome]:
        """Every student's reports, optionally narrowed."""
        ...

    async def reported_keys(
        self, student_ids: Collection[UUID]
    ) -> set[tuple[UUID, UUID, int]]:
        """(student, institution, cycle) of the students' reports."""
        ...

    async def nudge_targets(self) -> list[NudgeTarget]:
        """Students with the institution on a live list or marked interested."""
        ...
