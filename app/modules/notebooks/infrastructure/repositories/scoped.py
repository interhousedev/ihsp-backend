"""Session-per-call adapters: each call runs in its own committed transaction."""

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

    async def list(self, emis_subject_id: int, topic: str | None) -> list[BankQuestion]:
        """Every question of the subject (and topic)."""
        async with self.sessionmaker() as session:
            return await SqlQuestionBankStore(session).list(emis_subject_id, topic)


class ScopedTopicCatalog:
    """`SubjectTopicCatalog` read per call."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Bind the database."""
        self.sessionmaker = sessionmaker

    async def topics(self, emis_subject_id: int) -> tuple[str, ...] | None:
        """The subject's topics, or None when unknown."""
        async with self.sessionmaker() as session:
            return await SqlSubjectTopicCatalog(session).topics(emis_subject_id)
