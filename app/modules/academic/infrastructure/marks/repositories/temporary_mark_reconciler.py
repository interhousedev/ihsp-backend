"""SQL reconciliation of temporary marks with synced EMIS marks (TMP-2)."""

import datetime as dt
from collections.abc import Collection
from uuid import UUID

from app.modules.academic.infrastructure.classwork.temporary_mark_repository import (
    delete_in_emis,
)

from sqlalchemy.ext.asyncio import AsyncSession


class SqlTemporaryMarkReconciler:
    """Implements TemporaryMarkReconciler on an open session."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the unit of work's session."""
        self.session = session

    async def delete_in_emis(
        self, student_id: UUID, subject_id: UUID, dates: Collection[dt.date]
    ) -> int:
        """Delete the student's temporary marks of the subject on these dates."""
        return await delete_in_emis(self.session, student_id, subject_id, dates)
