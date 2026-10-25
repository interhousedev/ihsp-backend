"""SQLAlchemy repository of course steps."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.lms.domain.authoring.entities import CourseStep
from app.modules.lms.domain.authoring.enums import StepVia
from app.modules.lms.domain.authoring.errors import StepNotFoundError
from app.modules.lms.infrastructure.orm import CourseStep as StepRow

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession


class SqlStepRepository:
    """Reads and writes `lms.course_steps`."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the unit of work's session."""
        self.session = session

    async def get(self, step_id: UUID) -> CourseStep | None:
        """Return the step, or None."""
        row = await self._row(step_id)
        return None if row is None else _to_entity(row)

    async def get_locked(self, step_id: UUID) -> CourseStep | None:
        """Return the step and lock its row until the transaction ends."""
        row = await self._row(step_id, lock=True)
        return None if row is None else _to_entity(row)

    async def get_many(self, step_ids: Sequence[UUID]) -> dict[UUID, CourseStep]:
        """Return the steps that exist, by ID."""
        if not step_ids:
            return {}
        statement = (
            select(StepRow)
            .where(StepRow.id.in_(list(step_ids)))
            .execution_options(populate_existing=True)
        )
        return {r.id: _to_entity(r) for r in (await self.session.scalars(statement))}

    async def list_for_course(self, course_id: UUID) -> list[CourseStep]:
        """Return every step of the course."""
        statement = (
            select(StepRow)
            .where(StepRow.course_id == course_id)
            .order_by(StepRow.created_at, StepRow.id)
            .execution_options(populate_existing=True)
        )
        return [_to_entity(r) for r in (await self.session.scalars(statement))]

    async def add(self, step: CourseStep) -> None:
        """Insert a step."""
        row = StepRow()
        row.id = step.id
        row.course_id = step.course_id
        row.created_via = step.created_via.value
        row.live_revision_id = step.live_revision_id
        row.live_hash = step.live_hash
        _apply_draft(row, step)
        self.session.add(row)
        await self.session.flush()

    async def save_draft(self, step: CourseStep) -> None:
        """Write the draft, its hash, files, lock version and author fields."""
        row = await self._row(step.id)
        if row is None:
            raise StepNotFoundError(params={"step_id": str(step.id)})
        _apply_draft(row, step)
        await self.session.flush()

    async def set_live(
        self, step_id: UUID, *, revision_id: UUID, live_hash: str
    ) -> None:
        """Point the step at the revision of the live version."""
        await self.session.execute(
            update(StepRow)
            .where(StepRow.id == step_id)
            .values(live_revision_id=revision_id, live_hash=live_hash)
            .execution_options(synchronize_session=False)
        )

    async def clear_live(self, step_ids: Sequence[UUID]) -> None:
        """Clear the live pointers of steps that left the live version."""
        if not step_ids:
            return
        await self.session.execute(
            update(StepRow)
            .where(StepRow.id.in_(list(step_ids)))
            .values(live_revision_id=None, live_hash=None)
            .execution_options(synchronize_session=False)
        )

    async def _row(self, step_id: UUID, *, lock: bool = False) -> StepRow | None:
        statement = (
            select(StepRow)
            .where(StepRow.id == step_id)
            .execution_options(populate_existing=True)
        )
        if lock:
            statement = statement.with_for_update()
        return (await self.session.scalars(statement)).one_or_none()


def _to_entity(row: StepRow) -> CourseStep:
    return CourseStep(
        id=row.id,
        course_id=row.course_id,
        draft=row.draft,
        draft_hash=row.draft_hash,
        created_via=StepVia(row.created_via),
        draft_updated_via=StepVia(row.draft_updated_via),
        draft_updated_by=row.draft_updated_by,
        draft_updated_at=row.draft_updated_at,
        file_ids=list(row.file_ids),
        lock_version=row.lock_version,
        live_revision_id=row.live_revision_id,
        live_hash=row.live_hash,
    )


def _apply_draft(row: StepRow, step: CourseStep) -> None:
    row.draft = step.draft
    row.draft_hash = step.draft_hash
    row.draft_updated_by = step.draft_updated_by
    row.draft_updated_at = step.draft_updated_at
    row.draft_updated_via = step.draft_updated_via.value
    row.file_ids = list(step.file_ids)
    row.lock_version = step.lock_version
