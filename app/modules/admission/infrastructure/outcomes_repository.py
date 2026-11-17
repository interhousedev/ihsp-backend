"""SQL repository of self-reported outcomes and the nudge audience."""

from collections.abc import Collection
from typing import cast
from uuid import UUID

from app.modules.admission.domain.documents import LIVE_ENTRY_STATUSES
from app.modules.admission.domain.errors import (
    AdmissionConflictError,
    AdmissionNotFoundError,
)
from app.modules.admission.domain.outcomes import NudgeTarget, Outcome, OutcomeStatus
from app.modules.admission.infrastructure.orm.applications import ListEntryRow
from app.modules.admission.infrastructure.orm.matching import DecisionRow
from app.modules.admission.infrastructure.orm.outcomes import ApplicationOutcomeRow

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


def _outcome(row: ApplicationOutcomeRow) -> Outcome:
    return Outcome(
        id=row.id,
        student_id=row.student_id,
        institution_id=row.institution_id,
        cycle=row.cycle,
        plan=row.plan,
        status=cast(OutcomeStatus, row.status),
        share_name=row.share_name,
        lock_version=row.lock_version,
        updated_at=row.updated_at,
    )


class SqlOutcomeRepository:
    """Reports of application results, unique per student, institution, cycle."""

    def __init__(self, session: AsyncSession) -> None:
        """Keep the open session."""
        self._s = session

    async def list_for(self, student_id: UUID) -> list[Outcome]:
        """The student's reports, newest cycle first."""
        rows = await self._s.scalars(
            select(ApplicationOutcomeRow)
            .where(ApplicationOutcomeRow.student_id == student_id)
            .order_by(
                ApplicationOutcomeRow.cycle.desc(), ApplicationOutcomeRow.created_at
            )
        )
        return [_outcome(r) for r in rows]

    async def get(self, outcome_id: UUID) -> Outcome | None:
        """One report."""
        row = await self._s.get(ApplicationOutcomeRow, outcome_id)
        return _outcome(row) if row else None

    async def find(
        self, student_id: UUID, institution_id: UUID, cycle: int
    ) -> Outcome | None:
        """The report of a cycle at an institution."""
        row = await self._s.scalar(
            select(ApplicationOutcomeRow).where(
                ApplicationOutcomeRow.student_id == student_id,
                ApplicationOutcomeRow.institution_id == institution_id,
                ApplicationOutcomeRow.cycle == cycle,
            )
        )
        return _outcome(row) if row else None

    async def add(self, outcome: Outcome) -> Outcome:
        """Insert; a second report of the same cycle raises a conflict."""
        row = ApplicationOutcomeRow(
            id=outcome.id,
            student_id=outcome.student_id,
            institution_id=outcome.institution_id,
            cycle=outcome.cycle,
            plan=outcome.plan,
            status=outcome.status,
            share_name=outcome.share_name,
            lock_version=0,
        )
        self._s.add(row)
        try:
            async with self._s.begin_nested():
                await self._s.flush()
        except IntegrityError as exc:
            raise AdmissionConflictError() from exc
        await self._s.refresh(row)
        return _outcome(row)

    async def save(self, outcome: Outcome, *, expected_lock: int) -> Outcome:
        """Update; a stale lock raises a conflict."""
        row = await self._s.get(ApplicationOutcomeRow, outcome.id)
        if row is None:
            raise AdmissionNotFoundError()
        if row.lock_version != expected_lock:
            raise AdmissionConflictError()
        row.plan = outcome.plan
        row.status = outcome.status
        row.share_name = outcome.share_name
        row.lock_version = expected_lock + 1
        await self._s.flush()
        await self._s.refresh(row)
        return _outcome(row)

    async def delete(self, outcome_id: UUID) -> None:
        """Remove a report."""
        await self._s.execute(
            delete(ApplicationOutcomeRow).where(ApplicationOutcomeRow.id == outcome_id)
        )

    async def all(
        self, *, institution_id: UUID | None = None, cycle: int | None = None
    ) -> list[Outcome]:
        """Every student's reports, optionally narrowed."""
        stmt = select(ApplicationOutcomeRow)
        if institution_id is not None:
            stmt = stmt.where(ApplicationOutcomeRow.institution_id == institution_id)
        if cycle is not None:
            stmt = stmt.where(ApplicationOutcomeRow.cycle == cycle)
        rows = await self._s.scalars(stmt)
        return [_outcome(r) for r in rows]

    async def reported_keys(
        self, student_ids: Collection[UUID]
    ) -> set[tuple[UUID, UUID, int]]:
        """(student, institution, cycle) of the students' reports."""
        if not student_ids:
            return set()
        rows = await self._s.execute(
            select(
                ApplicationOutcomeRow.student_id,
                ApplicationOutcomeRow.institution_id,
                ApplicationOutcomeRow.cycle,
            ).where(ApplicationOutcomeRow.student_id.in_(list(student_ids)))
        )
        return {(s, i, c) for s, i, c in rows.tuples().all()}

    async def nudge_targets(self) -> list[NudgeTarget]:
        """Students with the institution on a live list or marked interested."""
        entries = await self._s.execute(
            select(
                ListEntryRow.student_id,
                ListEntryRow.institution_id,
                ListEntryRow.decision_at,
            ).where(ListEntryRow.status.in_(sorted(LIVE_ENTRY_STATUSES)))
        )
        targets = {(s, i): NudgeTarget(s, i, d) for s, i, d in entries.tuples().all()}
        interests = await self._s.execute(
            select(DecisionRow.student_id, DecisionRow.institution_id).where(
                DecisionRow.decision == "interested"
            )
        )
        for s, i in interests.tuples().all():
            targets.setdefault((s, i), NudgeTarget(s, i))
        return list(targets.values())
