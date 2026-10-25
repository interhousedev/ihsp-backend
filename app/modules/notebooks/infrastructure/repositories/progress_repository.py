"""SQL repository of the student's progress in flash card decks and quizzes."""

from uuid import UUID

from app.modules.notebooks.domain.entities import ArtifactProgress
from app.modules.notebooks.infrastructure.orm.artifact_progress import (
    ArtifactProgress as ProgressRow,
)

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession


class SqlProgressRepository:
    """Progress in `notebooks.artifact_progress`."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the unit of work's session."""
        self.session = session

    async def get(self, artifact_id: UUID, user_id: UUID) -> ArtifactProgress | None:
        """Return the student's progress."""
        stmt = (
            select(ProgressRow)
            .where(
                ProgressRow.artifact_id == artifact_id, ProgressRow.user_id == user_id
            )
            .execution_options(populate_existing=True)
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return None
        return ArtifactProgress(
            artifact_id=row.artifact_id,
            user_id=row.user_id,
            state=dict(row.state),
            updated_at=row.updated_at,
        )

    async def upsert(self, progress: ArtifactProgress) -> None:
        """Insert or replace the state."""
        stmt = insert(ProgressRow).values(
            artifact_id=progress.artifact_id,
            user_id=progress.user_id,
            state=progress.state,
            updated_at=progress.updated_at,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[ProgressRow.artifact_id, ProgressRow.user_id],
            set_={"state": stmt.excluded.state, "updated_at": stmt.excluded.updated_at},
        )
        await self.session.execute(stmt)

    async def delete_for_user(self, user_id: UUID) -> None:
        """Forget the user's progress everywhere (the account is deleted)."""
        await self.session.execute(
            delete(ProgressRow).where(ProgressRow.user_id == user_id),
            execution_options={"synchronize_session": False},
        )
