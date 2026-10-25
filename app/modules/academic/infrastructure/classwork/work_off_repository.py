"""SQL repositories for work-off templates and work-off tasks."""

import datetime as dt
from collections.abc import Collection, Sequence
from typing import Any, cast
from uuid import UUID

from app.modules.academic.domain.classwork.work_off import (
    ResolvedWorkOff,
    WorkOff,
    WorkOffStatus,
    WorkOffTemplate,
)
from app.modules.academic.infrastructure.orm.work_off import WorkOff as WorkOffRow
from app.modules.academic.infrastructure.orm.work_off import (
    WorkOffTemplate as TemplateRow,
)
from app.shared.ids import new_id

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession


def template_of(row: Any) -> WorkOffTemplate:
    """Map an ORM row or result row to the entity."""
    return WorkOffTemplate(
        id=row.id,
        teacher_id=row.teacher_id,
        text=row.text,
        is_default=row.is_default,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def work_off_of(row: Any) -> WorkOff:
    """Map an ORM row or result row to the entity."""
    return WorkOff(
        id=row.id,
        lesson_id=row.lesson_id,
        student_id=row.student_id,
        assigned_by=row.assigned_by,
        template_id=row.template_id,
        text=row.text,
        status=cast(WorkOffStatus, row.status),
        due_date=row.due_date,
        done_at=row.done_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SqlWorkOffTemplateRepository:
    """Implements WorkOffTemplateRepository on an open session."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the unit of work's session."""
        self.session = session

    async def list_for_teacher(self, teacher_id: UUID) -> list[WorkOffTemplate]:
        """The teacher's templates, oldest first."""
        stmt = (
            sa.select(TemplateRow)
            .where(TemplateRow.teacher_id == teacher_id)
            .order_by(TemplateRow.created_at, TemplateRow.id)
        )
        return [template_of(r) for r in (await self.session.scalars(stmt)).all()]

    async def get(self, template_id: UUID) -> WorkOffTemplate | None:
        """Return the template or None."""
        row = await self.session.get(TemplateRow, template_id)
        return None if row is None else template_of(row)

    async def get_many(
        self, template_ids: Sequence[UUID], teacher_id: UUID
    ) -> list[WorkOffTemplate]:
        """The templates among these ids that belong to the teacher."""
        if not template_ids:
            return []
        stmt = sa.select(TemplateRow).where(
            TemplateRow.id.in_(list(template_ids)), TemplateRow.teacher_id == teacher_id
        )
        return [template_of(r) for r in (await self.session.scalars(stmt)).all()]

    async def add(self, template: WorkOffTemplate) -> None:
        """Insert a template."""
        self.session.add(
            TemplateRow(
                id=template.id,
                teacher_id=template.teacher_id,
                text=template.text,
                is_default=template.is_default,
                created_at=template.created_at,
                updated_at=template.updated_at,
            )
        )
        await self.session.flush()

    async def update(
        self, template_id: UUID, *, text: str, is_default: bool, at: dt.datetime
    ) -> WorkOffTemplate:
        """Change text and default flag; return the row."""
        stmt = (
            sa.update(TemplateRow)
            .where(TemplateRow.id == template_id)
            .values(text=text, is_default=is_default, updated_at=at)
            .returning(TemplateRow)
        )
        return template_of((await self.session.scalars(stmt)).one())

    async def clear_defaults(
        self, template_ids: Collection[UUID], at: dt.datetime
    ) -> None:
        """Drop the default flag from these templates."""
        if template_ids:
            await self.session.execute(
                sa.update(TemplateRow)
                .where(TemplateRow.id.in_(list(template_ids)))
                .values(is_default=False, updated_at=at)
            )

    async def delete(self, template_id: UUID) -> None:
        """Delete a template (work-offs keep their text)."""
        await self.session.execute(
            sa.delete(TemplateRow).where(TemplateRow.id == template_id)
        )


class SqlWorkOffRepository:
    """Implements WorkOffRepository on an open session."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the unit of work's session."""
        self.session = session

    async def get(self, work_off_id: UUID) -> WorkOff | None:
        """Return the work-off or None."""
        row = await self.session.get(WorkOffRow, work_off_id)
        return None if row is None else work_off_of(row)

    async def for_lesson(self, lesson_id: UUID) -> list[WorkOff]:
        """The lesson's work-offs, oldest first."""
        return await self.for_lessons([lesson_id])

    async def for_lessons(self, lesson_ids: Sequence[UUID]) -> list[WorkOff]:
        """Work-offs of several lessons."""
        if not lesson_ids:
            return []
        stmt = (
            sa.select(WorkOffRow)
            .where(WorkOffRow.lesson_id.in_(list(lesson_ids)))
            .order_by(WorkOffRow.created_at, WorkOffRow.id)
        )
        return [work_off_of(r) for r in (await self.session.scalars(stmt)).all()]

    async def upsert(
        self,
        *,
        lesson_id: UUID,
        student_id: UUID,
        assigned_by: UUID,
        resolved: ResolvedWorkOff,
        at: dt.datetime,
    ) -> WorkOff:
        """Create the work-off or replace its task (status goes back to assigned)."""
        values = {
            "assigned_by": assigned_by,
            "template_id": resolved.template_id,
            "text": resolved.text,
            "due_date": resolved.due_date,
        }
        stmt = pg_insert(WorkOffRow).values(
            id=new_id(),
            lesson_id=lesson_id,
            student_id=student_id,
            status="assigned",
            created_at=at,
            updated_at=at,
            **values,
        )
        upsert = stmt.on_conflict_do_update(
            index_elements=[WorkOffRow.lesson_id, WorkOffRow.student_id],
            set_={**values, "status": "assigned", "done_at": None, "updated_at": at},
        ).returning(WorkOffRow)
        return work_off_of((await self.session.scalars(upsert)).one())

    async def update(
        self,
        work_off_id: UUID,
        *,
        text: str,
        due_date: dt.date | None,
        status: WorkOffStatus,
        done_at: dt.datetime | None,
        at: dt.datetime,
    ) -> WorkOff:
        """Overwrite the editable fields; return the row."""
        stmt = (
            sa.update(WorkOffRow)
            .where(WorkOffRow.id == work_off_id)
            .values(
                text=text,
                due_date=due_date,
                status=status,
                done_at=done_at,
                updated_at=at,
            )
            .returning(WorkOffRow)
        )
        return work_off_of((await self.session.scalars(stmt)).one())

    async def delete(self, work_off_id: UUID) -> None:
        """Delete one work-off."""
        await self.session.execute(
            sa.delete(WorkOffRow).where(WorkOffRow.id == work_off_id)
        )

    async def delete_for_students(
        self, lesson_id: UUID, student_ids: Collection[UUID]
    ) -> None:
        """Delete the lesson's work-offs of these students."""
        if student_ids:
            await self.session.execute(
                sa.delete(WorkOffRow).where(
                    WorkOffRow.lesson_id == lesson_id,
                    WorkOffRow.student_id.in_(list(student_ids)),
                )
            )

    async def delete_unless_absent(
        self, lesson_id: UUID, absent: Collection[UUID]
    ) -> list[UUID]:
        """Delete the lesson's work-offs of students not in ``absent``; return them."""
        stmt = sa.delete(WorkOffRow).where(WorkOffRow.lesson_id == lesson_id)
        if absent:
            stmt = stmt.where(WorkOffRow.student_id.not_in(list(absent)))
        done = await self.session.execute(stmt.returning(WorkOffRow.student_id))
        return [row[0] for row in done.all()]
