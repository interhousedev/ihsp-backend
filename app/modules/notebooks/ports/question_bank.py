"""Ports of the question bank."""

from typing import Protocol
from uuid import UUID

from app.modules.notebooks.domain.question_bank import BankQuestion


class QuestionBankStore(Protocol):
    """Persistent questions."""

    async def add(self, question: BankQuestion) -> None:
        """Insert a question."""
        ...

    async def get(self, question_id: UUID) -> BankQuestion | None:
        """One question or None."""
        ...

    async def replace(self, question: BankQuestion) -> None:
        """Overwrite a stored question."""
        ...

    async def delete(self, question_id: UUID) -> None:
        """Remove a question."""
        ...

    async def list(self, emis_subject_id: int, topic: str | None) -> list[BankQuestion]:
        """Every question of the subject (and topic), whoever owns it."""
        ...


class SubjectTopicCatalog(Protocol):
    """The academic topic directory filled from the EMIS thematic plan."""

    async def topics(self, emis_subject_id: int) -> tuple[str, ...] | None:
        """The subject's topics, or None when the EMIS subject is unknown."""
        ...
