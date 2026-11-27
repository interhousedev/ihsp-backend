"""Question bank rows and the EMIS topic directory."""

from typing import Any, cast
from uuid import UUID

from app.modules.notebooks.domain.question_bank import BankQuestion
from app.modules.notebooks.infrastructure.orm.question_bank import QuestionBankRow

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession


def _entity(row: QuestionBankRow) -> BankQuestion:
    return BankQuestion(
        id=row.id,
        owner_id=row.owner_id,
        emis_subject_id=row.emis_subject_id,
        topic=row.topic,
        question=row.question,
        answer=row.answer,
        options=tuple(row.options),
        explanation=row.explanation,
        difficulty=cast(Any, row.difficulty),
        origin=cast(Any, row.origin),
        visibility=cast(Any, row.visibility),
        created_at=row.created_at,
    )


def _values(q: BankQuestion) -> dict[str, Any]:
    return {
        "owner_id": q.owner_id,
        "emis_subject_id": q.emis_subject_id,
        "topic": q.topic,
        "question": q.question,
        "answer": q.answer,
        "options": list(q.options),
        "explanation": q.explanation,
        "difficulty": q.difficulty,
        "origin": q.origin,
        "visibility": q.visibility,
        "created_at": q.created_at,
    }


class SqlQuestionBankStore:
    """`QuestionBankStore` over `notebooks.question_bank`."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the store to the unit of work's session."""
        self.session = session

    async def add(self, question: BankQuestion) -> None:
        """Insert a question."""
        self.session.add(QuestionBankRow(id=question.id, **_values(question)))
        await self.session.flush()

    async def get(self, question_id: UUID) -> BankQuestion | None:
        """One question or None."""
        row = await self.session.get(QuestionBankRow, question_id)
        return None if row is None else _entity(row)

    async def replace(self, question: BankQuestion) -> None:
        """Overwrite a stored question."""
        row = await self.session.get(QuestionBankRow, question.id)
        if row is not None:
            for name, value in _values(question).items():
                setattr(row, name, value)
            await self.session.flush()

    async def list(self, emis_subject_id: int, topic: str | None) -> list[BankQuestion]:
        """Every question of the subject (and topic)."""
        stmt = select(QuestionBankRow).where(
            QuestionBankRow.emis_subject_id == emis_subject_id
        )
        if topic is not None:
            stmt = stmt.where(QuestionBankRow.topic == topic)
        rows = (await self.session.execute(stmt)).scalars().all()
        return [_entity(row) for row in rows]


class SqlSubjectTopicCatalog:
    """`SubjectTopicCatalog` over `academic.curriculum_topics` (read only)."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the catalogue to a session."""
        self.session = session

    async def topics(self, emis_subject_id: int) -> tuple[str, ...] | None:
        """The subject's topics in plan order; None when the subject is unknown."""
        known = await self.session.execute(
            text("SELECT 1 FROM academic.subjects WHERE emis_subject_id = :s"),
            {"s": emis_subject_id},
        )
        if known.first() is None:
            return None
        rows = await self.session.execute(
            text(
                "SELECT topic FROM academic.curriculum_topics "
                "WHERE emis_subject_id = :s "
                "GROUP BY topic ORDER BY min(semester), min(position), topic"
            ),
            {"s": emis_subject_id},
        )
        return tuple(r[0] for r in rows)
