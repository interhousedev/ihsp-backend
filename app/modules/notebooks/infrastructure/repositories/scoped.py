"""Session-per-call adapters: each call runs in its own committed transaction."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.modules.notebooks.domain.question_bank import BankQuestion
from app.modules.notebooks.infrastructure.repositories.material_sink_repository import (
    SqlNotebookDirectory,
    SqlSourceWriter,
)
from app.modules.notebooks.infrastructure.repositories.question_bank_repository import (
    SqlQuestionBankStore,
    SqlSubjectTopicCatalog,
)

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class ScopedNotebookDirectory:
    """`NotebookDirectory` that commits per call."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Bind the database."""
        self.sessionmaker = sessionmaker

    async def subject_notebook(
        self, owner_id: UUID, subject_id: UUID, group_id: UUID | None
    ) -> UUID:
        """Find or create the notebook."""
        async with self.sessionmaker.begin() as session:
            return await SqlNotebookDirectory(session).subject_notebook(
                owner_id, subject_id, group_id
            )


class ScopedSourceWriter:
    """`SourceWriter` that commits per call."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Bind the database."""
        self.sessionmaker = sessionmaker

    async def add_text(self, **fields: Any) -> Any:
        """Add the text source."""
        async with self.sessionmaker.begin() as session:
            source = await SqlSourceWriter(session).add_text(**fields)
            return source.id


class ScopedQuestionBank:
    """`QuestionBankStore` that commits per call."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Bind the database."""
        self.sessionmaker = sessionmaker

    async def add(self, question: BankQuestion) -> None:
        """Insert a question."""
        async with self.sessionmaker.begin() as session:
            await SqlQuestionBankStore(session).add(question)

    async def get(self, question_id: UUID) -> BankQuestion | None:
        """One question or None."""
        async with self.sessionmaker() as session:
            return await SqlQuestionBankStore(session).get(question_id)

    async def replace(self, question: BankQuestion) -> None:
        """Overwrite a stored question."""
        async with self.sessionmaker.begin() as session:
            await SqlQuestionBankStore(session).replace(question)

    async def delete(self, question_id: UUID) -> None:
        """Remove a question."""
        async with self.sessionmaker.begin() as session:
            await SqlQuestionBankStore(session).delete(question_id)

    async def add_many(self, questions: Sequence[BankQuestion]) -> None:
        """Insert several questions in one transaction."""
        async with self.sessionmaker.begin() as session:
            await SqlQuestionBankStore(session).add_many(questions)

    async def visible_texts(
        self, emis_subject_id: int, topic: str, viewer_id: UUID
    ) -> list[tuple[UUID, str]]:
        """(id, text) of the topic's questions the viewer sees."""
        async with self.sessionmaker() as session:
            return await SqlQuestionBankStore(session).visible_texts(
                emis_subject_id, topic, viewer_id
            )

    async def visible_ids(
        self,
        emis_subject_id: int,
        topic: str,
        viewer_id: UUID,
        difficulty: str | None,
    ) -> list[UUID]:
        """Ids of the viewer's visible questions, oldest first."""
        async with self.sessionmaker() as session:
            return await SqlQuestionBankStore(session).visible_ids(
                emis_subject_id, topic, viewer_id, difficulty
            )

    async def get_many(self, ids: Sequence[UUID]) -> list[BankQuestion]:
        """The questions with these ids, in order."""
        async with self.sessionmaker() as session:
            return await SqlQuestionBankStore(session).get_many(ids)

    async def count_by_topic(
        self, emis_subject_id: int, viewer_id: UUID
    ) -> dict[str, int]:
        """Visible question count per topic."""
        async with self.sessionmaker() as session:
            return await SqlQuestionBankStore(session).count_by_topic(
                emis_subject_id, viewer_id
            )

    async def page(
        self,
        emis_subject_id: int,
        topic: str | None,
        viewer_id: UUID | None,
        limit: int,
        offset: int,
    ) -> tuple[list[BankQuestion], int]:
        """One page, newest first, and the total."""
        async with self.sessionmaker() as session:
            return await SqlQuestionBankStore(session).page(
                emis_subject_id, topic, viewer_id, limit, offset
            )


class ScopedTopicCatalog:
    """`SubjectTopicCatalog` read per call."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Bind the database."""
        self.sessionmaker = sessionmaker

    async def topics(self, emis_subject_id: int) -> tuple[str, ...] | None:
        """The subject's topics, or None when unknown."""
        async with self.sessionmaker() as session:
            return await SqlSubjectTopicCatalog(session).topics(emis_subject_id)
