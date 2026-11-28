"""Port: a teacher's homework defaults."""

import datetime as dt
from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from app.modules.academic.domain.classwork.records import TeacherHomeworkSettings


class HomeworkSettingsRepository(Protocol):
    """Rows of ``academic.teacher_homework_settings``; no row means the defaults."""

    async def get(self, teacher_id: UUID) -> TeacherHomeworkSettings:
        """The teacher's settings (the defaults when nothing was saved)."""
        ...

    async def get_many(
        self, teacher_ids: Sequence[UUID]
    ) -> dict[UUID, TeacherHomeworkSettings]:
        """Saved settings by teacher; teachers without a row are absent."""
        ...

    async def save(
        self,
        teacher_id: UUID,
        *,
        accept_by_default: bool | None,
        notify_on_submission: bool | None,
        now: dt.datetime,
    ) -> TeacherHomeworkSettings:
        """Create or update the row; ``None`` keeps a field."""
        ...
