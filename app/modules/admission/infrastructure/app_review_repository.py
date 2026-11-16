"""SQL storage of the full application reviews."""

from uuid import UUID

from app.modules.admission.domain.app_review import AppReview
from app.modules.admission.infrastructure.orm.app_review import AppReviewRow

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _domain(row: AppReviewRow) -> AppReview:
    return AppReview(
        id=row.id,
        student_id=row.student_id,
        version=row.version,
        status=row.status,  # type: ignore[arg-type]
        locale=row.locale,
        created_by=row.created_by,
        created_at=row.created_at,
        staff_visible=row.staff_visible,
        sections=list(row.sections or []),
        report=row.report,
        models=list(row.models or []),
        error_code=row.error_code,
        started_at=row.started_at,
        finished_at=row.finished_at,
    )


class SqlAppReviewRepository:
    """Each call opens and commits its own session (the job runs for minutes)."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Keep the sessionmaker."""
        self._sm = sessionmaker

    async def add(self, review: AppReview) -> AppReview:
        """Insert the next version of the student."""
        async with self._sm() as session, session.begin():
            last = await session.scalar(
                select(func.max(AppReviewRow.version)).where(
                    AppReviewRow.student_id == review.student_id
                )
            )
            review.version = int(last or 0) + 1
            session.add(
                AppReviewRow(
                    id=review.id,
                    student_id=review.student_id,
                    version=review.version,
                    status=review.status,
                    locale=review.locale,
                    created_by=review.created_by,
                    created_at=review.created_at,
                    staff_visible=review.staff_visible,
                    sections=review.sections,
                    report=review.report,
                    models=review.models,
                )
            )
        return review

    async def get(self, review_id: UUID) -> AppReview | None:
        """Return one review."""
        async with self._sm() as session:
            row = await session.get(AppReviewRow, review_id)
            return None if row is None else _domain(row)

    async def list_for(self, student_id: UUID, *, limit: int = 20) -> list[AppReview]:
        """Return the newest versions first."""
        async with self._sm() as session:
            rows = await session.scalars(
                select(AppReviewRow)
                .where(AppReviewRow.student_id == student_id)
                .order_by(AppReviewRow.version.desc())
                .limit(limit)
            )
            return [_domain(r) for r in rows]

    async def save(self, review: AppReview) -> None:
        """Write status, results and timestamps."""
        async with self._sm() as session, session.begin():
            row = await session.get(AppReviewRow, review.id)
            if row is None:
                return
            row.status = review.status
            row.staff_visible = review.staff_visible
            row.sections = review.sections
            row.report = review.report
            row.models = review.models
            row.error_code = review.error_code
            row.started_at = review.started_at
            row.finished_at = review.finished_at
