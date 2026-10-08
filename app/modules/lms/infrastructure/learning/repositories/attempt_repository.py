"""SQLAlchemy repository of test attempts."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from app.modules.lms.domain.learning.entities import Attempt
from app.modules.lms.domain.learning.errors import AttemptNumberTakenError
from app.modules.lms.domain.learning.variant import Variant
from app.modules.lms.infrastructure.orm.course_step import CourseStep
from app.modules.lms.infrastructure.orm.test_attempt import TestAttempt as AttemptRow

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

# The unique index (user, step, block, attempt_no) where not is_preview.
ATTEMPT_NUMBER_COLUMN = "attempt_no"


def _to_entity(row: AttemptRow) -> Attempt:
    """Map the ORM row to the entity."""
    return Attempt(
        id=row.id,
        user_id=row.user_id,
        step_id=row.step_id,
        revision_id=row.revision_id,
        block_id=row.block_id,
        attempt_no=row.attempt_no,
        is_preview=row.is_preview,
        variant=Variant.from_json(row.variant),
        started_at=row.started_at,
        deadline_at=row.deadline_at,
        max_score=Decimal(row.max_score),
        submitted_at=row.submitted_at,
        answers=dict(row.answers or {}),
        score=None if row.score is None else Decimal(row.score),
        passed=row.passed,
        override_score=(
            None if row.override_score is None else Decimal(row.override_score)
        ),
        override_comment=row.override_comment,
        reviewed_by=row.reviewed_by,
        reviewed_at=row.reviewed_at,
    )


class SqlAttemptRepository:
    """Attempts of the lms schema."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to a session."""
        self.session = session

    async def add(self, attempt: Attempt) -> None:
        """Insert an attempt; a taken (user, step, block, number) is a domain error."""
        self.session.add(
            AttemptRow(
                id=attempt.id,
                user_id=attempt.user_id,
                step_id=attempt.step_id,
                revision_id=attempt.revision_id,
                block_id=attempt.block_id,
                attempt_no=attempt.attempt_no,
                is_preview=attempt.is_preview,
                variant=attempt.variant.to_json(),
                started_at=attempt.started_at,
                deadline_at=attempt.deadline_at,
                answers=attempt.answers or None,
                max_score=attempt.max_score,
            )
        )
        try:
            await self.session.flush()
        except IntegrityError as error:
            if ATTEMPT_NUMBER_COLUMN in str(error.orig):
                raise AttemptNumberTakenError() from error
            raise

    async def get(
        self, attempt_id: UUID, *, for_update: bool = False
    ) -> Attempt | None:
        """Return an attempt, optionally locking its row."""
        statement = (
            select(AttemptRow)
            .where(AttemptRow.id == attempt_id)
            .execution_options(populate_existing=True)
        )
        if for_update:
            statement = statement.with_for_update()
        row = await self.session.scalar(statement)
        return _to_entity(row) if row else None

    async def save(self, attempt: Attempt) -> None:
        """Store answers, result and review fields of the attempt."""
        await self.session.execute(
            update(AttemptRow)
            .where(AttemptRow.id == attempt.id)
            .values(
                answers=attempt.answers,
                submitted_at=attempt.submitted_at,
                score=attempt.score,
                max_score=attempt.max_score,
                passed=attempt.passed,
                override_score=attempt.override_score,
                override_comment=attempt.override_comment,
                reviewed_by=attempt.reviewed_by,
                reviewed_at=attempt.reviewed_at,
            )
            .execution_options(synchronize_session=False)
        )

    async def list_for_step(self, user_id: UUID, step_id: UUID) -> list[Attempt]:
        """Return the user's non-preview attempts in a step ordered by number."""
        rows = await self.session.scalars(
            select(AttemptRow)
            .where(
                AttemptRow.user_id == user_id,
                AttemptRow.step_id == step_id,
                AttemptRow.is_preview.is_(False),
            )
            .order_by(AttemptRow.block_id, AttemptRow.attempt_no)
            .execution_options(populate_existing=True)
        )
        return [_to_entity(row) for row in rows]

    async def list_open(
        self, user_id: UUID, step_id: UUID, *, preview: bool
    ) -> list[Attempt]:
        """Return the user's unsubmitted attempts in a step, newest first."""
        rows = await self.session.scalars(
            select(AttemptRow)
            .where(
                AttemptRow.user_id == user_id,
                AttemptRow.step_id == step_id,
                AttemptRow.is_preview.is_(preview),
                AttemptRow.submitted_at.is_(None),
            )
            .order_by(AttemptRow.started_at.desc(), AttemptRow.id.desc())
            .execution_options(populate_existing=True)
        )
        return [_to_entity(row) for row in rows]

    async def count(self, user_id: UUID, step_id: UUID, block_id: str) -> int:
        """Return how many non-preview attempts the user started in the block."""
        total = await self.session.scalar(
            select(func.count())
            .select_from(AttemptRow)
            .where(
                AttemptRow.user_id == user_id,
                AttemptRow.step_id == step_id,
                AttemptRow.block_id == block_id,
                AttemptRow.is_preview.is_(False),
            )
        )
        return int(total or 0)

    async def max_attempt_no(
        self, user_id: UUID, step_id: UUID, block_id: str, *, preview: bool
    ) -> int:
        """Return the highest attempt number used so far (0 if none)."""
        highest = await self.session.scalar(
            select(func.max(AttemptRow.attempt_no)).where(
                AttemptRow.user_id == user_id,
                AttemptRow.step_id == step_id,
                AttemptRow.block_id == block_id,
                AttemptRow.is_preview.is_(preview),
            )
        )
        return int(highest or 0)

    async def last_submitted_at(
        self, user_id: UUID, step_id: UUID, block_id: str
    ) -> datetime | None:
        """Return when the user last submitted a non-preview attempt in the block."""
        return await self.session.scalar(
            select(func.max(AttemptRow.submitted_at)).where(
                AttemptRow.user_id == user_id,
                AttemptRow.step_id == step_id,
                AttemptRow.block_id == block_id,
                AttemptRow.is_preview.is_(False),
            )
        )

    async def passed_block_ids(self, user_id: UUID, step_id: UUID) -> set[str]:
        """Return the test blocks of the step with a passed non-preview attempt."""
        rows = await self.session.scalars(
            select(AttemptRow.block_id)
            .where(
                AttemptRow.user_id == user_id,
                AttemptRow.step_id == step_id,
                AttemptRow.is_preview.is_(False),
                AttemptRow.passed.is_(True),
            )
            .distinct()
        )
        return set(rows)

    async def list_submitted_for_course(self, course_id: UUID) -> list[Attempt]:
        """Return all submitted non-preview attempts in the course."""
        rows = await self.session.scalars(
            select(AttemptRow)
            .join(CourseStep, CourseStep.id == AttemptRow.step_id)
            .where(
                CourseStep.course_id == course_id,
                AttemptRow.is_preview.is_(False),
                AttemptRow.submitted_at.is_not(None),
            )
            .order_by(AttemptRow.submitted_at, AttemptRow.id)
            .execution_options(populate_existing=True)
        )
        return [_to_entity(row) for row in rows]
