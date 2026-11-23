"""SQLAlchemy store of AI review conversations."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.modules.lms.domain.learning.ai_review_errors import (
    AiReviewClosedError,
    AiReviewNoSubmissionsLeftError,
    AiReviewSessionNotFoundError,
)
from app.modules.lms.infrastructure.orm.ai_review import (
    AiReviewMessage,
    AiReviewSession,
)
from app.modules.lms.ports.learning.ai_review_store import (
    AiReviewMessageRecord,
    AiReviewSessionRecord,
    AiReviewStatus,
    NewAiReviewMessage,
)

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from uuid_utils.compat import uuid7


def _session(row: AiReviewSession) -> AiReviewSessionRecord:
    return AiReviewSessionRecord(
        id=row.id,
        course_id=row.course_id,
        step_id=row.step_id,
        block_id=row.block_id,
        user_id=row.user_id,
        status=row.status,  # type: ignore[arg-type]
        submissions_used=row.submissions_used,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _message(row: AiReviewMessage) -> AiReviewMessageRecord:
    attachments: list[dict[str, Any]] = list(row.attachments or [])
    return AiReviewMessageRecord(
        id=row.id,
        session_id=row.session_id,
        role=row.role,  # type: ignore[arg-type]
        kind=row.kind,  # type: ignore[arg-type]
        text=row.text,
        openui=row.openui,
        history=row.history,
        attachments=attachments,
        created_at=row.created_at,
    )


class SqlAiReviewStore:
    """AiReviewStore on its own short transactions."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Store the session factory."""
        self.sessionmaker = sessionmaker

    async def create_session(
        self, *, course_id: UUID, step_id: UUID, block_id: str, user_id: UUID
    ) -> AiReviewSessionRecord:
        """Insert an open session."""
        async with self.sessionmaker() as db:
            row = AiReviewSession(
                id=uuid7(),
                course_id=course_id,
                step_id=step_id,
                block_id=block_id,
                user_id=user_id,
                status="open",
                submissions_used=0,
            )
            db.add(row)
            await db.flush()
            await db.refresh(row)
            record = _session(row)
            await db.commit()
        return record

    async def get_session(self, session_id: UUID) -> AiReviewSessionRecord | None:
        """Return the session or None."""
        async with self.sessionmaker() as db:
            row = await db.get(AiReviewSession, session_id)
            return _session(row) if row is not None else None

    async def list_sessions(
        self, *, step_id: UUID, block_id: str, user_id: UUID | None = None
    ) -> Sequence[AiReviewSessionRecord]:
        """Sessions of a block (of one user when given), newest first."""
        query = select(AiReviewSession).where(
            AiReviewSession.step_id == step_id, AiReviewSession.block_id == block_id
        )
        if user_id is not None:
            query = query.where(AiReviewSession.user_id == user_id)
        async with self.sessionmaker() as db:
            rows = await db.scalars(query.order_by(AiReviewSession.id.desc()))
            return [_session(r) for r in rows]

    async def messages(self, session_id: UUID) -> Sequence[AiReviewMessageRecord]:
        """Messages of a session in order (uuid7 ids sort by time)."""
        async with self.sessionmaker() as db:
            rows = await db.scalars(
                select(AiReviewMessage)
                .where(AiReviewMessage.session_id == session_id)
                .order_by(AiReviewMessage.id)
            )
            return [_message(r) for r in rows]

    async def append(
        self,
        session_id: UUID,
        messages: Sequence[NewAiReviewMessage],
        *,
        status: AiReviewStatus | None = None,
        add_submission: bool = False,
    ) -> list[AiReviewMessageRecord]:
        """Append messages and update the session in one transaction.

        The session row is locked, so of two concurrent turns only the first may
        close it; the second finds it reviewed and raises AiReviewClosedError.
        """
        async with self.sessionmaker() as db:
            session = await db.get(AiReviewSession, session_id, with_for_update=True)
            if session is None:
                return []
            if session.status == "reviewed":
                raise AiReviewClosedError(params={"session_id": str(session_id)})
            rows = [
                AiReviewMessage(
                    id=uuid7(),
                    session_id=session_id,
                    role=m.role,
                    kind=m.kind,
                    text=m.text,
                    openui=m.openui,
                    history=m.history,
                    attachments=m.attachments,
                )
                for m in messages
            ]
            db.add_all(rows)
            if status is not None:
                session.status = status
            if add_submission:
                session.submissions_used += 1
            await db.flush()
            for row in rows:
                await db.refresh(row)
            records = [_message(r) for r in rows]
            await db.commit()
        return records

    async def reserve_submission(
        self, session_id: UUID, *, max_submissions: int
    ) -> AiReviewSessionRecord:
        """Lock the student's sessions of the block, check the limit, spend one."""
        async with self.sessionmaker() as db:
            session = await db.get(AiReviewSession, session_id)
            if session is None:
                raise AiReviewSessionNotFoundError(
                    params={"session_id": str(session_id)}
                )
            rows = list(
                await db.scalars(
                    select(AiReviewSession)
                    .where(
                        AiReviewSession.step_id == session.step_id,
                        AiReviewSession.block_id == session.block_id,
                        AiReviewSession.user_id == session.user_id,
                    )
                    .order_by(AiReviewSession.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            )
            own = next(r for r in rows if r.id == session_id)
            if own.status == "reviewed":
                raise AiReviewClosedError(params={"session_id": str(session_id)})
            if sum(r.submissions_used for r in rows) >= max_submissions:
                raise AiReviewNoSubmissionsLeftError(params={"max": max_submissions})
            own.submissions_used += 1
            await db.flush()
            await db.refresh(own)
            record = _session(own)
            await db.commit()
        return record

    async def refund_submission(self, session_id: UUID) -> None:
        """Give one reserved submission back, never below zero."""
        async with self.sessionmaker() as db:
            session = await db.get(AiReviewSession, session_id, with_for_update=True)
            if session is not None:
                session.submissions_used = max(session.submissions_used - 1, 0)
                await db.commit()
