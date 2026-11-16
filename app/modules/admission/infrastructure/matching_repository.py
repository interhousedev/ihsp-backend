"""SQL repositories of preference answers and swipe decisions."""

import dataclasses
import datetime as dt
from uuid import UUID

from app.modules.admission.domain.matching import PreferenceAnswers
from app.modules.admission.infrastructure.orm.matching import (
    DecisionRow,
    StudentPreferenceRow,
)
from app.shared.ids import new_id

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

_FIELDS = {f.name for f in dataclasses.fields(PreferenceAnswers)}


class SqlPreferenceRepository:
    """One answers row per student."""

    def __init__(self, session: AsyncSession) -> None:
        """Keep the open session."""
        self._s = session

    async def get(
        self, student_id: UUID
    ) -> tuple[PreferenceAnswers, dt.datetime] | None:
        """The answers and when they were saved."""
        row = await self._s.get(StudentPreferenceRow, student_id)
        if row is None:
            return None
        known = {k: v for k, v in row.answers.items() if k in _FIELDS}
        return PreferenceAnswers(**known), row.updated_at

    async def save(
        self, student_id: UUID, answers: PreferenceAnswers, now: dt.datetime
    ) -> None:
        """Insert or replace the answers."""
        payload = {
            k: v for k, v in dataclasses.asdict(answers).items() if v is not None
        }
        await self._s.execute(
            insert(StudentPreferenceRow)
            .values(student_id=student_id, answers=payload, updated_at=now)
            .on_conflict_do_update(
                index_elements=[StudentPreferenceRow.student_id],
                set_={"answers": payload, "updated_at": now},
            )
        )


class SqlDecisionRepository:
    """Swipes, unique per student and university."""

    def __init__(self, session: AsyncSession) -> None:
        """Keep the open session."""
        self._s = session

    async def decided(self, student_id: UUID) -> dict[UUID, str]:
        """University id → decision."""
        rows = await self._s.execute(
            select(DecisionRow.institution_id, DecisionRow.decision).where(
                DecisionRow.student_id == student_id
            )
        )
        return dict(rows.tuples().all())

    async def get(self, student_id: UUID, institution_id: UUID) -> str | None:
        """The decision on one university."""
        decision: str | None = await self._s.scalar(
            select(DecisionRow.decision).where(
                DecisionRow.student_id == student_id,
                DecisionRow.institution_id == institution_id,
            )
        )
        return decision

    async def created_entry(self, student_id: UUID, institution_id: UUID) -> bool:
        """Whether the swipe itself put the university on the list."""
        created = await self._s.scalar(
            select(DecisionRow.created_list_entry).where(
                DecisionRow.student_id == student_id,
                DecisionRow.institution_id == institution_id,
            )
        )
        return bool(created)

    async def set(
        self,
        student_id: UUID,
        institution_id: UUID,
        decision: str,
        now: dt.datetime,
        *,
        created_list_entry: bool = False,
    ) -> None:
        """Insert or replace the decision."""
        await self._s.execute(
            insert(DecisionRow)
            .values(
                id=new_id(),
                student_id=student_id,
                institution_id=institution_id,
                decision=decision,
                decided_at=now,
                created_list_entry=created_list_entry,
            )
            .on_conflict_do_update(
                constraint="uq_university_decisions_student_institution",
                set_={
                    "decision": decision,
                    "decided_at": now,
                    "created_list_entry": created_list_entry,
                },
            )
        )

    async def delete(self, student_id: UUID, institution_id: UUID) -> None:
        """Forget the decision."""
        await self._s.execute(
            delete(DecisionRow).where(
                DecisionRow.student_id == student_id,
                DecisionRow.institution_id == institution_id,
            )
        )
