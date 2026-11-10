"""SQLAlchemy implementation of the excuse repository."""

import datetime as dt
from collections.abc import Sequence
from uuid import UUID

from app.modules.academic.domain.excuses.excuse import (
    Excuse,
    ExcuseMessage,
    ExcuseOrigin,
    ExcuseStatus,
    ExcuseTemplate,
)
from app.modules.academic.infrastructure.orm import excuse as orm

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession


def _to_excuse(row: orm.Excuse) -> Excuse:
    return Excuse(
        id=row.id,
        student_id=row.student_id,
        origin=ExcuseOrigin(row.origin),
        status=ExcuseStatus(row.status),
        template_id=row.template_id,
        reason=row.reason,
        starts_on=row.starts_on,
        ends_on=row.ends_on,
        lesson_ids=tuple(row.lesson_ids),
        subject_ids=tuple(row.subject_ids),
        created_by=row.created_by,
        decided_by=row.decided_by,
        decided_at=row.decided_at,
        decision_comment=row.decision_comment,
        version=row.version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_message(row: orm.ExcuseMessage) -> ExcuseMessage:
    return ExcuseMessage(
        id=row.id,
        excuse_id=row.excuse_id,
        author_id=row.author_id,
        body=row.body,
        file_ids=tuple(row.file_ids),
        created_at=row.created_at,
    )


class SqlExcuseRepository:
    """Implements ExcuseRepository on one session."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the session of the unit of work."""
        self.session = session

    async def add(self, excuse: Excuse) -> None:
        """Insert a new excuse."""
        self.session.add(
            orm.Excuse(
                id=excuse.id,
                student_id=excuse.student_id,
                origin=excuse.origin.value,
                status=excuse.status.value,
                template_id=excuse.template_id,
                reason=excuse.reason,
                starts_on=excuse.starts_on,
                ends_on=excuse.ends_on,
                lesson_ids=list(excuse.lesson_ids),
                subject_ids=list(excuse.subject_ids),
                created_by=excuse.created_by,
                decided_by=excuse.decided_by,
                decided_at=excuse.decided_at,
                decision_comment=excuse.decision_comment,
                version=excuse.version,
                created_at=excuse.created_at,
                updated_at=excuse.updated_at,
            )
        )
        await self.session.flush()

    async def get(self, excuse_id: UUID) -> Excuse | None:
        """Return the excuse (without its thread) or None."""
        row = await self.session.get(orm.Excuse, excuse_id)
        return _to_excuse(row) if row else None

    async def save(self, excuse: Excuse) -> None:
        """Write the changed state, version and update time."""
        await self.session.execute(
            update(orm.Excuse)
            .where(orm.Excuse.id == excuse.id)
            .values(
                status=excuse.status.value,
                ends_on=excuse.ends_on,
                decided_by=excuse.decided_by,
                decided_at=excuse.decided_at,
                decision_comment=excuse.decision_comment,
                version=excuse.version,
                updated_at=excuse.updated_at,
            )
        )

    async def search(
        self,
        *,
        student_ids: Sequence[UUID] | None,
        status: ExcuseStatus | None,
        offset: int,
        limit: int,
    ) -> list[Excuse]:
        """Newest first; ``student_ids`` None means every student."""
        stmt = select(orm.Excuse)
        if student_ids is not None:
            stmt = stmt.where(orm.Excuse.student_id.in_(list(student_ids)))
        if status is not None:
            stmt = stmt.where(orm.Excuse.status == status.value)
        stmt = (
            stmt.order_by(orm.Excuse.created_at.desc(), orm.Excuse.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return [_to_excuse(row) for row in (await self.session.scalars(stmt)).all()]

    async def covering(self, student_ids: Sequence[UUID], day: dt.date) -> list[Excuse]:
        """Approved excuses of the students whose period includes the day."""
        if not student_ids:
            return []
        stmt = select(orm.Excuse).where(
            orm.Excuse.student_id.in_(list(student_ids)),
            orm.Excuse.status == ExcuseStatus.APPROVED.value,
            orm.Excuse.starts_on <= day,
            (orm.Excuse.ends_on.is_(None)) | (orm.Excuse.ends_on >= day),
        )
        return [_to_excuse(row) for row in (await self.session.scalars(stmt)).all()]

    async def add_message(self, message: ExcuseMessage) -> None:
        """Append a line to the thread."""
        self.session.add(
            orm.ExcuseMessage(
                id=message.id,
                excuse_id=message.excuse_id,
                author_id=message.author_id,
                body=message.body,
                file_ids=list(message.file_ids),
                created_at=message.created_at,
            )
        )
        await self.session.flush()

    async def messages(self, excuse_id: UUID) -> list[ExcuseMessage]:
        """The thread, oldest first."""
        stmt = (
            select(orm.ExcuseMessage)
            .where(orm.ExcuseMessage.excuse_id == excuse_id)
            .order_by(orm.ExcuseMessage.created_at, orm.ExcuseMessage.id)
        )
        return [_to_message(r) for r in (await self.session.scalars(stmt)).all()]

    async def templates(self, *, active_only: bool) -> list[ExcuseTemplate]:
        """Templates in their display order."""
        stmt = select(orm.ExcuseTemplate).order_by(
            orm.ExcuseTemplate.sort, orm.ExcuseTemplate.code
        )
        if active_only:
            stmt = stmt.where(orm.ExcuseTemplate.active.is_(True))
        return [
            ExcuseTemplate(
                id=row.id,
                code=row.code,
                title={str(k): str(v) for k, v in row.title.items()},
                requires_document=row.requires_document,
                active=row.active,
                sort=row.sort,
            )
            for row in (await self.session.scalars(stmt)).all()
        ]
