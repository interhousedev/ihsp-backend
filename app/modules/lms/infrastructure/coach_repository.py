"""SQLAlchemy stores of the Coach: sessions, solution keys, insights."""

from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.lms.domain.learning.coach import (
    CoachMode,
    CoachOutcome,
    KeyStatus,
    Misconception,
    SolutionKey,
    TutorSession,
    TutorTurn,
)
from app.modules.lms.infrastructure.orm.course_step import CourseStep
from app.modules.lms.infrastructure.orm.step_revision import StepRevision
from app.modules.lms.infrastructure.orm.tutor import TutorSession as SessionRow
from app.modules.lms.infrastructure.orm.tutor import TutorTurn as TurnRow
from app.modules.lms.ports.coach import CoachInsightRow
from app.shared.ids import new_id

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _session(row: SessionRow, turns: list[TurnRow]) -> TutorSession:
    return TutorSession(
        id=row.id,
        enrollment_id=row.enrollment_id,
        step_id=row.step_id,
        block_id=row.block_id,
        mode=CoachMode(row.mode),
        opened_at=row.opened_at,
        revision_id=row.revision_id,
        closed_at=row.closed_at,
        outcome=None if row.outcome is None else CoachOutcome(row.outcome),
        turns=[
            TutorTurn(
                row.id, t.role, t.text, t.hint_level, list(t.citations), t.created_at
            )
            for t in turns
        ],
        hint_level=row.hint_level,
    )


async def _load(db: AsyncSession, row: SessionRow | None) -> TutorSession | None:
    if row is None:
        return None
    turns = await db.scalars(
        select(TurnRow)
        .where(TurnRow.session_id == row.id)
        .order_by(TurnRow.created_at, TurnRow.id)
    )
    return _session(row, list(turns))


class SqlTutorSessionRepository:
    """Sessions of the lms schema; every lookup is scoped by the learner."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Bind to the session factory."""
        self.sessionmaker = sessionmaker

    async def add(self, user_id: UUID, session: TutorSession) -> None:
        """Insert a new session."""
        async with self.sessionmaker() as db:
            db.add(
                SessionRow(
                    id=session.id,
                    user_id=user_id,
                    enrollment_id=session.enrollment_id,
                    step_id=session.step_id,
                    block_id=session.block_id,
                    revision_id=session.revision_id,
                    mode=session.mode.value,
                    hint_level=session.hint_level,
                    opened_at=session.opened_at,
                )
            )
            await db.commit()

    async def save(self, user_id: UUID, session: TutorSession) -> None:
        """Persist the ladder, the outcome and the turns not stored yet."""
        async with self.sessionmaker() as db:
            row = await db.scalar(
                select(SessionRow)
                .where(SessionRow.id == session.id, SessionRow.user_id == user_id)
                .with_for_update()
            )
            if row is None:
                raise LookupError(str(session.id))
            row.hint_level = session.hint_level
            row.closed_at = session.closed_at
            row.outcome = None if session.outcome is None else session.outcome.value
            stored = await db.scalar(
                select(func.count())
                .select_from(TurnRow)
                .where(TurnRow.session_id == session.id)
            )
            for turn in session.turns[stored or 0 :]:
                db.add(
                    TurnRow(
                        id=new_id(),
                        session_id=session.id,
                        role=turn.role,
                        text=turn.text,
                        hint_level=turn.hint_level,
                        citations=list(turn.citations),
                        created_at=turn.created_at,
                    )
                )
            await db.commit()

    async def get_for_user(
        self, session_id: UUID, user_id: UUID
    ) -> TutorSession | None:
        """Return the session, or None for another learner's id."""
        async with self.sessionmaker() as db:
            row = await db.scalar(
                select(SessionRow).where(
                    SessionRow.id == session_id, SessionRow.user_id == user_id
                )
            )
            return await _load(db, row)

    async def latest_for_step(
        self, user_id: UUID, step_id: UUID
    ) -> TutorSession | None:
        """Return the learner's newest session on the step."""
        async with self.sessionmaker() as db:
            row = await db.scalar(
                select(SessionRow)
                .where(SessionRow.user_id == user_id, SessionRow.step_id == step_id)
                .order_by(SessionRow.opened_at.desc(), SessionRow.id.desc())
                .limit(1)
            )
            return await _load(db, row)


def dump_key(key: SolutionKey) -> dict[str, Any]:
    """Return the stored JSON form of a key."""
    return {
        "block_id": key.block_id,
        "question_id": key.question_id,
        "steps": list(key.steps),
        "misconceptions": [
            {"pattern": m.pattern, "nudge": m.nudge} for m in key.misconceptions
        ],
        "status": key.status.value,
        "answers": list(key.answers),
    }


def _key(step_id: UUID, data: dict[str, Any]) -> SolutionKey:
    return SolutionKey(
        step_id=step_id,
        block_id=data["block_id"],
        question_id=data["question_id"],
        steps=list(data.get("steps", [])),
        misconceptions=[
            Misconception(m["pattern"], m["nudge"])
            for m in data.get("misconceptions", [])
        ],
        status=KeyStatus(data.get("status", "draft")),
        answers=list(data.get("answers", [])),
    )


class SqlSolutionKeyRepository:
    """Solution keys stored in the `solution_keys` column of a revision."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Bind to the session factory."""
        self.sessionmaker = sessionmaker

    async def for_revision(self, revision_id: UUID) -> list[SolutionKey]:
        """Return the keys of one revision only."""
        async with self.sessionmaker() as db:
            row = await db.get(StepRevision, revision_id)
            if row is None:
                return []
            return [_key(row.step_id, d) for d in row.solution_keys]

    async def replace(self, revision_id: UUID, keys: list[SolutionKey]) -> None:
        """Store the keys of a revision."""
        async with self.sessionmaker() as db:
            row = await db.get(StepRevision, revision_id)
            if row is None:
                raise LookupError(str(revision_id))
            row.solution_keys = [dump_key(k) for k in keys]
            await db.commit()


class SqlCoachInsights:
    """Aggregates the sessions of a course by step."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Bind to the session factory."""
        self.sessionmaker = sessionmaker

    async def for_course(
        self, course_id: UUID, start: datetime | None, end: datetime | None
    ) -> list[CoachInsightRow]:
        """Return one row per step with sessions in the period."""
        query = (
            select(
                SessionRow.step_id,
                func.count(),
                func.count(case((SessionRow.outcome == "resolved", 1))),
                func.count(case((SessionRow.outcome == "escalated", 1))),
                func.max(SessionRow.hint_level),
            )
            .join(CourseStep, CourseStep.id == SessionRow.step_id)
            .where(CourseStep.course_id == course_id)
            .group_by(SessionRow.step_id)
            .order_by(SessionRow.step_id)
        )
        if start is not None:
            query = query.where(SessionRow.opened_at >= start)
        if end is not None:
            query = query.where(SessionRow.opened_at < end)
        async with self.sessionmaker() as db:
            rows = (await db.execute(query)).all()
        return [CoachInsightRow(r[0], r[1], r[2], r[3], r[4] or 0) for r in rows]
