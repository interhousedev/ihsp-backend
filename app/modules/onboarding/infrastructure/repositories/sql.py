"""SQL repository of onboarding progress."""

from uuid import UUID

from app.modules.onboarding.domain.steps import Progress
from app.modules.onboarding.infrastructure.orm import OnboardingProgressRow

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession


class SqlProgressRepository:
    """Progress rows."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the session."""
        self.session = session

    async def get(self, user_id: UUID) -> Progress | None:
        """Return the row or None."""
        row = await self.session.get(OnboardingProgressRow, user_id)
        if row is None:
            return None
        return Progress(
            user_id=row.user_id,
            created_at=row.created_at,
            certificates_prompt_done_at=row.certificates_prompt_done_at,
            completed_at=row.completed_at,
        )

    async def save(self, progress: Progress) -> None:
        """Insert or replace the user's row."""
        values = {
            "user_id": progress.user_id,
            "certificates_prompt_done_at": progress.certificates_prompt_done_at,
            "completed_at": progress.completed_at,
            "created_at": progress.created_at,
        }
        stmt = insert(OnboardingProgressRow).values(values)
        await self.session.execute(
            stmt.on_conflict_do_update(
                index_elements=[OnboardingProgressRow.user_id],
                set_={
                    **{
                        k: v
                        for k, v in values.items()
                        if k not in ("user_id", "created_at")
                    },
                    "updated_at": func.now(),
                },
            )
        )
