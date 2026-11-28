"""Ports of the question bank."""

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from app.modules.notebooks.domain.question_bank import BankQuestion
from app.shared.actor import Actor


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

    async def add_many(self, questions: Sequence[BankQuestion]) -> None:
        """Insert several questions in one statement."""
        ...

    async def visible_texts(
        self, emis_subject_id: int, topic: str, viewer_id: UUID
    ) -> list[tuple[UUID, str]]:
        """(id, text) of the topic's questions the viewer owns or that are shared."""
        ...

    async def visible_ids(
        self,
        emis_subject_id: int,
        topic: str,
        viewer_id: UUID,
        difficulty: str | None,
    ) -> list[UUID]:
        """Ids of the viewer's visible questions, oldest first (created_at, id)."""
        ...

    async def get_many(self, ids: Sequence[UUID]) -> list[BankQuestion]:
        """The questions with these ids, in the order of `ids`."""
        ...

    async def count_by_topic(
        self, emis_subject_id: int, viewer_id: UUID
    ) -> dict[str, int]:
        """Visible question count per topic (topics without questions absent)."""
        ...

    async def page(
        self,
        emis_subject_id: int,
        topic: str | None,
        viewer_id: UUID | None,
        limit: int,
        offset: int,
    ) -> tuple[list[BankQuestion], int]:
        """One page, newest first, and the total; `viewer_id` None sees everything."""
        ...


class SubjectTeaching(Protocol):
    """Whether the actor may use the bank of an EMIS subject."""

    async def teaches(self, actor: Actor, emis_subject_id: int) -> bool:
        """True when the actor teaches the EMIS subject now; admins pass."""
        ...


class SubjectTopicCatalog(Protocol):
    """The academic topic directory filled from the EMIS thematic plan."""

    async def topics(self, emis_subject_id: int) -> tuple[str, ...] | None:
        """The subject's topics, or None when the EMIS subject is unknown."""
        ...
