"""Reads a handed-in homework for the teacher AI checks, scoped to the actor."""

from uuid import UUID

from app.modules.academic.infrastructure.orm.homework_submission import (
    HomeworkSubmission,
)
from app.modules.academic.infrastructure.orm.lesson import Lesson
from app.shared.actor import Actor, Role
from app.shared.base_error import NotFoundError
from app.shared.contracts.files import FilesApi
from app.shared.contracts.teacher_ai import SubmissionWork

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_TEXT_TYPES = ("text/",)
_FILE_CHARS = 20_000


class SqlSubmissionReader:
    """The submission's comment and text files; only the lesson's teacher or admin."""

    def __init__(
        self, sessionmaker: async_sessionmaker[AsyncSession], files: FilesApi
    ) -> None:
        """Bind the database and the files module."""
        self.sessionmaker = sessionmaker
        self.files = files

    async def read(self, actor: Actor, submission_id: UUID) -> SubmissionWork:
        """Return the work, or NotFoundError (unknown and foreign look the same)."""
        stmt = (
            sa.select(
                HomeworkSubmission.lesson_id,
                HomeworkSubmission.comment,
                HomeworkSubmission.file_ids,
                Lesson.teacher_id,
                Lesson.subject_id,
                Lesson.homework_text,
                Lesson.emis_topic,
                Lesson.emis_topic_description,
            )
            .join(Lesson, Lesson.id == HomeworkSubmission.lesson_id)
            .where(HomeworkSubmission.id == submission_id)
        )
        async with self.sessionmaker() as session:
            row = (await session.execute(stmt)).first()
        if row is None or not (
            actor.has(Role.ADMIN) or row.teacher_id == actor.user_id
        ):
            raise NotFoundError(params={"submission_id": str(submission_id)})
        parts = [row.comment] if row.comment else []
        refs = await self.files.get_many(list(row.file_ids))
        for file_id in row.file_ids:
            ref = refs.get(file_id)
            if ref is not None and ref.content_type.startswith(_TEXT_TYPES):
                data = await self.files.read_bytes(file_id)
                parts.append(data.decode(errors="replace")[:_FILE_CHARS])
        return SubmissionWork(
            # EMIS-only homework: the topic stands in for the missing task text.
            row.homework_text or row.emis_topic_description or row.emis_topic or "",
            "\n\n".join(parts),
            row.subject_id,
            None,
            row.lesson_id,
        )
