"""Which homework submissions a stored file is attached to (safe delete)."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.academic.infrastructure.classwork.sql_helpers import uuid_array
from app.modules.academic.infrastructure.orm.homework_submission import (
    HomeworkSubmission,
)

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class SqlSubmissionFileUsage:
    """Answers ``used_by_files`` from the handed-in submissions."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Store the session factory."""
        self.sessionmaker = sessionmaker

    async def used_by_files(
        self, file_ids: Sequence[UUID]
    ) -> dict[UUID, list[tuple[str, UUID, str]]]:
        """Return ``("lesson", lesson_id, "homework")`` per handed-in file."""
        if not file_ids:
            return {}
        wanted = set(file_ids)
        async with self.sessionmaker() as session:
            rows = (
                await session.execute(
                    select(
                        HomeworkSubmission.file_ids, HomeworkSubmission.lesson_id
                    ).where(
                        HomeworkSubmission.file_ids.op("&&", is_comparison=True)(
                            uuid_array(list(wanted))
                        )
                    )
                )
            ).all()
        used: dict[UUID, list[tuple[str, UUID, str]]] = {}
        for attached, lesson_id in rows:
            for file_id in wanted.intersection(attached):
                entry = ("lesson", lesson_id, "homework")
                places = used.setdefault(file_id, [])
                if entry not in places:
                    places.append(entry)
        return used
