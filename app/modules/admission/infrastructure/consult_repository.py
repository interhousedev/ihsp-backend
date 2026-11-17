"""SQL repositories: consultations, quiz answers and profile interests."""

import datetime as dt
from collections.abc import Collection
from typing import Any, cast
from uuid import UUID

from app.modules.admission.domain.consultations import (
    Consultation,
    ConsultFormat,
    ConsultStatus,
    LinkedKind,
    WithKind,
)
from app.modules.admission.domain.errors import (
    AdmissionConflictError,
    AdmissionNotFoundError,
)
from app.modules.admission.domain.profile_details import Interests, QuizAnswers
from app.modules.admission.infrastructure.orm.consultations import (
    ConsultationRow,
    ProfileDetailsRow,
    QuizAnswersRow,
)

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession


def _consultation(r: ConsultationRow) -> Consultation:
    return Consultation(
        id=r.id,
        student_id=r.student_id,
        with_kind=cast(WithKind, r.with_kind),
        topic=r.topic,
        linked_kind=cast(LinkedKind, r.linked_kind),
        linked_id=r.linked_id,
        details=r.details,
        preferred_times=tuple(r.preferred_times),
        format=cast(ConsultFormat, r.format),
        status=cast(ConsultStatus, r.status),
        staff_id=r.staff_id,
        scheduled_at=r.scheduled_at,
        location=r.location,
        staff_notes=r.staff_notes,
        decline_reason=r.decline_reason,
        created_at=r.created_at,
        updated_at=r.updated_at,
        completed_at=r.completed_at,
        lock_version=r.lock_version,
    )


def _fill(r: ConsultationRow, c: Consultation) -> None:
    r.status = c.status
    r.staff_id = c.staff_id
    r.scheduled_at = c.scheduled_at
    r.location = c.location
    r.staff_notes = c.staff_notes
    r.decline_reason = c.decline_reason
    r.completed_at = c.completed_at


class SqlConsultationRepository:
    """Consultation requests in `admission.consultations`."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the session."""
        self._s = session

    async def add(self, c: Consultation) -> Consultation:
        """Insert a request."""
        row = ConsultationRow(
            id=c.id,
            student_id=c.student_id,
            with_kind=c.with_kind,
            topic=c.topic,
            details=c.details,
            linked_kind=c.linked_kind,
            linked_id=c.linked_id,
            preferred_times=list(c.preferred_times),
            format=c.format,
            status=c.status,
            lock_version=0,
        )
        self._s.add(row)
        await self._s.flush()
        await self._s.refresh(row)
        return _consultation(row)

    async def get(self, consultation_id: UUID) -> Consultation | None:
        """Return the request."""
        row = await self._s.get(ConsultationRow, consultation_id)
        return _consultation(row) if row else None

    async def save(self, c: Consultation) -> Consultation:
        """Compare-and-set update."""
        row = await self._s.get(ConsultationRow, c.id, with_for_update=True)
        if row is None:
            raise AdmissionNotFoundError()
        if row.lock_version != c.lock_version:
            raise AdmissionConflictError()
        _fill(row, c)
        row.lock_version = c.lock_version + 1
        await self._s.flush()
        await self._s.refresh(row)
        return _consultation(row)

    async def of_student(self, student_id: UUID) -> list[Consultation]:
        """The student's requests, newest first."""
        rows = await self._s.scalars(
            select(ConsultationRow)
            .where(ConsultationRow.student_id == student_id)
            .order_by(ConsultationRow.created_at.desc())
        )
        return [_consultation(r) for r in rows]

    async def count_active(self, student_id: UUID) -> int:
        """Requests that are requested, proposed or accepted."""
        n = await self._s.scalar(
            select(func.count())
            .select_from(ConsultationRow)
            .where(
                ConsultationRow.student_id == student_id,
                ConsultationRow.status.in_(("requested", "proposed", "accepted")),
            )
        )
        return int(n or 0)

    async def for_staff(
        self,
        kinds: Collection[str],
        staff_id: UUID,
        statuses: Collection[str],
        *,
        all_staff: bool = False,
    ) -> list[Consultation]:
        """Open requests of the kinds plus the ones assigned to the staff member."""
        q = select(ConsultationRow).where(ConsultationRow.status.in_(list(statuses)))
        if not all_staff:
            q = q.where(
                or_(
                    ConsultationRow.staff_id == staff_id,
                    and_(
                        ConsultationRow.staff_id.is_(None),
                        ConsultationRow.with_kind.in_(list(kinds)),
                    ),
                )
            )
        rows = await self._s.scalars(q.order_by(ConsultationRow.created_at.desc()))
        return [_consultation(r) for r in rows]


class SqlProfileDetailsRepository:
    """Interests and quiz answers."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the session."""
        self._s = session

    async def get_interests(self, student_id: UUID) -> Interests:
        """Return the interests (empty when never saved)."""
        row = await self._s.get(ProfileDetailsRow, student_id)
        if row is None:
            return Interests()
        return Interests(tuple(row.interest_fields), tuple(row.service_interests))

    async def save_interests(
        self, student_id: UUID, interests: Interests, now: dt.datetime
    ) -> None:
        """Upsert the interests."""
        values: dict[str, Any] = {
            "student_id": student_id,
            "interest_fields": list(interests.fields),
            "service_interests": list(interests.services),
            "updated_at": now,
        }
        stmt = insert(ProfileDetailsRow).values(**values)
        await self._s.execute(
            stmt.on_conflict_do_update(
                index_elements=["student_id"],
                set_={k: v for k, v in values.items() if k != "student_id"},
            )
        )

    async def get_quiz(self, student_id: UUID, quiz: str) -> QuizAnswers | None:
        """Return the stored answers of a quiz."""
        row = await self._s.get(QuizAnswersRow, (student_id, quiz))
        if row is None:
            return None
        return QuizAnswers(student_id, quiz, dict(row.answers), row.completed)

    async def save_quiz(self, answers: QuizAnswers, now: dt.datetime) -> None:
        """Upsert the answers of a quiz."""
        values: dict[str, Any] = {
            "student_id": answers.student_id,
            "quiz": answers.quiz,
            "answers": dict(answers.answers),
            "completed": answers.completed,
            "updated_at": now,
        }
        stmt = insert(QuizAnswersRow).values(**values)
        await self._s.execute(
            stmt.on_conflict_do_update(
                index_elements=["student_id", "quiz"],
                set_={
                    k: v for k, v in values.items() if k not in ("student_id", "quiz")
                },
            )
        )

    async def completed_quizzes(self, student_id: UUID) -> frozenset[str]:
        """Quizzes the student finished."""
        rows = await self._s.scalars(
            select(QuizAnswersRow.quiz).where(
                QuizAnswersRow.student_id == student_id,
                QuizAnswersRow.completed.is_(True),
            )
        )
        return frozenset(rows)
