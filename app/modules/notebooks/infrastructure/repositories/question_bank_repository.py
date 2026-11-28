"""Question bank rows and the EMIS topic directory."""

from collections.abc import Sequence
from typing import Any, cast
from uuid import UUID

from app.modules.notebooks.domain.question_bank import BankQuestion
from app.modules.notebooks.infrastructure.orm.question_bank import QuestionBankRow

from sqlalchemy import ColumnElement, func, insert, or_, select, text
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

    async def delete(self, question_id: UUID) -> None:
        """Remove a question."""
        row = await self.session.get(QuestionBankRow, question_id)
        if row is not None:
            await self.session.delete(row)
            await self.session.flush()

    async def add_many(self, questions: Sequence[BankQuestion]) -> None:
        """Insert several questions in one statement."""
        if questions:
            await self.session.execute(
                insert(QuestionBankRow),
                [{"id": q.id, **_values(q)} for q in questions],
            )

    @staticmethod
    def _visible(viewer_id: UUID) -> ColumnElement[bool]:
        return or_(
            QuestionBankRow.owner_id == viewer_id,
            QuestionBankRow.visibility == "subject",
        )

    async def visible_texts(
        self, emis_subject_id: int, topic: str, viewer_id: UUID
    ) -> list[tuple[UUID, str]]:
        """(id, text) of the topic's questions the viewer owns or that are shared."""
        stmt = select(QuestionBankRow.id, QuestionBankRow.question).where(
            QuestionBankRow.emis_subject_id == emis_subject_id,
            QuestionBankRow.topic == topic,
            self._visible(viewer_id),
        )
        return [(r[0], r[1]) for r in (await self.session.execute(stmt)).all()]

    async def visible_ids(
        self,
        emis_subject_id: int,
        topic: str,
        viewer_id: UUID,
        difficulty: str | None,
    ) -> list[UUID]:
        """Ids of the viewer's visible questions, oldest first (created_at, id)."""
        stmt = (
            select(QuestionBankRow.id)
            .where(
                QuestionBankRow.emis_subject_id == emis_subject_id,
                QuestionBankRow.topic == topic,
                self._visible(viewer_id),
            )
            .order_by(QuestionBankRow.created_at, QuestionBankRow.id)
        )
        if difficulty is not None:
            stmt = stmt.where(QuestionBankRow.difficulty == difficulty)
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_many(self, ids: Sequence[UUID]) -> list[BankQuestion]:
        """The questions with these ids, in the order of `ids`."""
        if not ids:
            return []
        stmt = select(QuestionBankRow).where(QuestionBankRow.id.in_(ids))
        found = {r.id: r for r in (await self.session.execute(stmt)).scalars()}
        return [_entity(found[i]) for i in ids if i in found]

    async def count_by_topic(
        self, emis_subject_id: int, viewer_id: UUID
    ) -> dict[str, int]:
        """Visible question count per topic (topics without questions absent)."""
        stmt = (
            select(QuestionBankRow.topic, func.count())
            .where(
                QuestionBankRow.emis_subject_id == emis_subject_id,
                self._visible(viewer_id),
            )
            .group_by(QuestionBankRow.topic)
        )
        return {r[0]: r[1] for r in (await self.session.execute(stmt)).all()}

    async def page(
        self,
        emis_subject_id: int,
        topic: str | None,
        viewer_id: UUID | None,
        limit: int,
        offset: int,
    ) -> tuple[list[BankQuestion], int]:
        """One page, newest first, and the total; `viewer_id` None sees everything."""
        where: list[ColumnElement[bool]] = [
            QuestionBankRow.emis_subject_id == emis_subject_id
        ]
        if topic is not None:
            where.append(QuestionBankRow.topic == topic)
        if viewer_id is not None:
            where.append(self._visible(viewer_id))
        total = (
            await self.session.execute(
                select(func.count()).select_from(QuestionBankRow).where(*where)
            )
        ).scalar_one()
        stmt = (
            select(QuestionBankRow)
            .where(*where)
            .order_by(QuestionBankRow.created_at.desc(), QuestionBankRow.id.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [_entity(r) for r in rows], total


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
