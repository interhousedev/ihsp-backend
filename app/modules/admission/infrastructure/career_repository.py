"""SQL repository of the career inventory, majors and plans."""

from typing import Any, cast
from uuid import UUID

from app.modules.admission.domain.career import (
    CareerMajor,
    CareerPlan,
    CareerQuestion,
    CareerSection,
    MajorFit,
    Profession,
    Spike,
    SpikeEvidence,
)
from app.modules.admission.domain.errors import AdmissionConflictError
from app.modules.admission.infrastructure.orm.career import (
    CareerMajorRow,
    CareerPlanRow,
    CareerQuestionRow,
)
from app.shared.ids import new_id

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


def _question(row: CareerQuestionRow) -> CareerQuestion:
    return CareerQuestion(
        id=row.id,
        section=cast(CareerSection, row.section),
        prompt=dict(row.prompt),
        sort_order=row.sort_order,
        active=row.active,
    )


def _major(row: CareerMajorRow) -> CareerMajor:
    return CareerMajor(
        id=row.id,
        code=row.code,
        area=row.area,
        name=dict(row.name),
        minor_ok=row.minor_ok,
        sort_order=row.sort_order,
        active=row.active,
    )


def _spike_json(spike: Spike | None) -> dict[str, Any] | None:
    if spike is None:
        return None
    return {
        "title": spike.title,
        "summary": spike.summary,
        "evidence": [
            {"item_id": str(e.item_id), "note": e.note} for e in spike.evidence
        ],
        "gaps": list(spike.gaps),
    }


def _plan(row: CareerPlanRow) -> CareerPlan:
    spike = None
    if row.spike:
        spike = Spike(
            title=row.spike["title"],
            summary=row.spike["summary"],
            evidence=tuple(
                SpikeEvidence(item_id=UUID(e["item_id"]), note=e["note"])
                for e in row.spike.get("evidence", [])
            ),
            gaps=tuple(row.spike.get("gaps", [])),
            confirmed_at=row.spike_confirmed_at,
        )
    return CareerPlan(
        student_id=row.student_id,
        answers=dict(row.answers),
        professions=[Profession(**p) for p in row.professions],
        majors=list(row.majors),
        minors=list(row.minors),
        fit=[MajorFit(**f) for f in row.fit],
        spike=spike,
        lock_version=row.lock_version,
    )


class SqlCareerRepository:
    """Career rows on an open session."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the session."""
        self._s = session

    async def questions(self, *, active_only: bool) -> list[CareerQuestion]:
        """Return the questions by section and sort order."""
        q = select(CareerQuestionRow).order_by(
            CareerQuestionRow.sort_order, CareerQuestionRow.id
        )
        if active_only:
            q = q.where(CareerQuestionRow.active.is_(True))
        return [_question(r) for r in await self._s.scalars(q)]

    async def get_question(self, question_id: UUID) -> CareerQuestion | None:
        """Return one question."""
        row = await self._s.get(CareerQuestionRow, question_id)
        return _question(row) if row else None

    async def save_question(self, question: CareerQuestion) -> CareerQuestion:
        """Insert or update a question."""
        row = await self._s.get(CareerQuestionRow, question.id)
        if row is None:
            row = CareerQuestionRow(id=question.id or new_id())
            self._s.add(row)
        row.section = question.section
        row.prompt = question.prompt
        row.sort_order = question.sort_order
        row.active = question.active
        await self._s.flush()
        await self._s.refresh(row)
        return _question(row)

    async def majors(self, *, active_only: bool) -> list[CareerMajor]:
        """Return the majors by area and sort order."""
        q = select(CareerMajorRow).order_by(
            CareerMajorRow.area, CareerMajorRow.sort_order, CareerMajorRow.code
        )
        if active_only:
            q = q.where(CareerMajorRow.active.is_(True))
        return [_major(r) for r in await self._s.scalars(q)]

    async def get_major(self, major_id: UUID) -> CareerMajor | None:
        """Return one major."""
        row = await self._s.get(CareerMajorRow, major_id)
        return _major(row) if row else None

    async def save_major(self, major: CareerMajor) -> CareerMajor:
        """Insert or update a major; a taken code is a conflict."""
        row = await self._s.get(CareerMajorRow, major.id)
        if row is None:
            row = CareerMajorRow(id=major.id or new_id())
            self._s.add(row)
        row.code = major.code
        row.area = major.area
        row.name = major.name
        row.minor_ok = major.minor_ok
        row.sort_order = major.sort_order
        row.active = major.active
        try:
            async with self._s.begin_nested():
                await self._s.flush()
        except IntegrityError as exc:
            raise AdmissionConflictError() from exc
        await self._s.refresh(row)
        return _major(row)

    async def plan(self, student_id: UUID) -> CareerPlan | None:
        """Return the student's plan."""
        row = await self._s.get(CareerPlanRow, student_id)
        return _plan(row) if row else None

    async def save_plan(self, plan: CareerPlan) -> CareerPlan:
        """Insert or store the plan and bump the lock version (compare-and-set)."""
        row = await self._s.get(CareerPlanRow, plan.student_id, with_for_update=True)
        if row is None:
            if plan.lock_version != 0:
                raise AdmissionConflictError()
            row = CareerPlanRow(student_id=plan.student_id, lock_version=0)
            self._s.add(row)
        elif row.lock_version != plan.lock_version:
            raise AdmissionConflictError()
        else:
            row.lock_version = plan.lock_version + 1
        row.answers = dict(plan.answers)
        row.professions = [
            {"title": p.title, "reason": p.reason, "shortlisted": p.shortlisted}
            for p in plan.professions
        ]
        row.majors = list(plan.majors)
        row.minors = list(plan.minors)
        row.fit = [
            {"code": f.code, "score": f.score, "reason": f.reason} for f in plan.fit
        ]
        row.spike = _spike_json(plan.spike)
        row.spike_confirmed_at = plan.spike.confirmed_at if plan.spike else None
        await self._s.flush()
        await self._s.refresh(row)
        return _plan(row)
