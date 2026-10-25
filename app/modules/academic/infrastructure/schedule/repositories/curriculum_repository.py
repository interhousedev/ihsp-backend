"""SQL repository of group curricula."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.academic.domain.curriculum.records import (
    Curriculum,
    SemesterSubject,
)
from app.modules.academic.infrastructure.orm import GroupCurriculum as CurriculumRow
from app.modules.academic.infrastructure.orm import (
    GroupCurriculumSubject as CurriculumSubjectRow,
)
from app.modules.academic.infrastructure.schedule.curriculum_mappers import (
    curriculum_to_entity,
    curriculum_values,
    subject_row_values,
    subject_to_entity,
)

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession


class SqlCurriculumRepository:
    """Group curricula in the academic schema."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to a session."""
        self.session = session

    async def get(self, group_id: UUID) -> Curriculum | None:
        """Return the group's stored curriculum header or None."""
        row = await self.session.get(CurriculumRow, group_id, populate_existing=True)
        return curriculum_to_entity(row) if row else None

    async def exists(self, group_id: UUID) -> bool:
        """Return True if the group has a stored curriculum."""
        stmt = select(CurriculumRow.group_id).where(CurriculumRow.group_id == group_id)
        return (await self.session.scalars(stmt.limit(1))).first() is not None

    async def save(self, curriculum: Curriculum) -> None:
        """Insert the group's curriculum header or replace the stored one."""
        await self._lock(curriculum.group_id)
        values = curriculum_values(curriculum)
        stmt = insert(CurriculumRow).values(group_id=curriculum.group_id, **values)
        await self.session.execute(
            stmt.on_conflict_do_update(
                index_elements=[CurriculumRow.group_id],
                set_={**values, "updated_at": func.now()},
            )
        )

    async def replace_subjects(
        self, group_id: UUID, subjects: Sequence[SemesterSubject]
    ) -> None:
        """Replace every semester subject of the group with the given ones."""
        await self._lock(group_id)
        await self.session.execute(
            delete(CurriculumSubjectRow).where(
                CurriculumSubjectRow.group_id == group_id
            )
        )
        if subjects:
            await self.session.execute(
                insert(CurriculumSubjectRow),
                [subject_row_values(group_id, subject) for subject in subjects],
            )

    async def list_subjects(self, group_id: UUID) -> list[SemesterSubject]:
        """Return the group's semester subjects ordered by semester and EMIS id."""
        stmt = (
            select(CurriculumSubjectRow)
            .where(CurriculumSubjectRow.group_id == group_id)
            .order_by(
                CurriculumSubjectRow.semester_number,
                CurriculumSubjectRow.emis_subject_id,
            )
        )
        return [subject_to_entity(row) for row in await self.session.scalars(stmt)]

    async def group_ids(self) -> list[UUID]:
        """Return the ids of the groups that have a stored curriculum."""
        stmt = select(CurriculumRow.group_id).order_by(CurriculumRow.group_id)
        return list(await self.session.scalars(stmt))

    async def _lock(self, group_id: UUID) -> None:
        """Serialize writers of one group's curriculum until the transaction ends."""
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
            {"key": f"academic.group_curriculum:{group_id}"},
        )
