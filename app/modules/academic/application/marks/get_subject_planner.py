"""The mark planner of one subject: prediction, targets and what-if (ACA-15)."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.modules.academic.application.marks.ports.unit_of_work import MarksUowFactory
from app.modules.academic.application.marks.view_context import (
    build_context,
    caller_locale,
    num,
)
from app.modules.academic.domain.marks import planner
from app.modules.academic.domain.marks.errors import (
    StudentNotFoundError,
    SubjectNotFoundError,
)
from app.modules.academic.domain.marks.read_models import MarkRow
from app.modules.academic.domain.marks.semesters import resolve_semester
from app.shared.actor import Actor
from app.shared.contracts.identity import IdentityDirectory


class GetSubjectPlanner:
    """Builds `SubjectPlanner` from the student's marks of one semester."""

    def __init__(
        self, *, uow_factory: MarksUowFactory, identity: IdentityDirectory
    ) -> None:
        """Store collaborators."""
        self._uow_factory = uow_factory
        self._identity = identity

    async def execute(
        self,
        actor: Actor,
        subject_id: UUID,
        semester: int | None,
        what_if: Sequence[planner.HypotheticalMark] = (),
    ) -> dict[str, Any]:
        """Return `SubjectPlanner`; raises SubjectNotFoundError for a foreign subject.

        ``what_if`` marks are added to the real ones for this answer only.
        """
        locale = await caller_locale(self._identity, actor.user_id)
        async with self._uow_factory() as uow:
            reader = uow.reader
            ctx = await reader.student_context(actor.user_id)
            if ctx is None:
                raise StudentNotFoundError()
            results = await reader.results(actor.user_id, None)
            sem = resolve_semester(
                semester, ctx.current_semester, {r.semester for r in results}
            )
            marks = await reader.marks(
                actor.user_id, semester=sem, subject_id=subject_id
            )
            known = subject_id in ctx.curriculum_subject_ids or bool(marks)
            view = await build_context(
                reader, self._identity, locale=locale, subject_ids=[subject_id]
            )
        if not known or subject_id not in view.subjects:
            raise SubjectNotFoundError(params={"subject_id": str(subject_id)})
        lesson, midterm, final = planner.add_hypothetical(
            _values(marks, "lesson"),
            _values(marks, "midterm"),
            _values(marks, "final"),
            what_if,
        )
        plan = planner.plan(lesson, midterm, final, what_if_count=len(what_if))
        return _view(view.subject_ref(subject_id), sem, plan, what_if)


def _values(marks: Sequence[MarkRow], mark_type: str) -> list[int]:
    return [m.value for m in marks if m.type == mark_type]


def _stat(stat: planner.MarkStat) -> dict[str, Any]:
    return {"count": stat.count, "average": num(stat.average)}


def _target(target: planner.TargetPlan) -> dict[str, Any]:
    return {
        "grade": target.grade,
        "threshold": num(target.threshold),
        "status": target.status,
        "control": target.control,
        "min_value": target.min_value,
        "min_both": target.min_both,
        "pairs": [
            {"midterm": p.midterm, "min_final": p.min_final} for p in target.pairs
        ],
    }


def _view(
    subject: dict[str, Any],
    semester: int,
    plan: planner.Plan,
    what_if: Sequence[planner.HypotheticalMark],
) -> dict[str, Any]:
    return {
        "subject": subject,
        "semester": semester,
        "lesson": _stat(plan.lesson),
        "midterm": _stat(plan.midterm),
        "final": _stat(plan.final),
        "semester_mark": num(plan.semester_mark),
        "components": list(plan.components),
        "missing": list(plan.missing),
        "remaining": {
            "midterm": plan.remaining.midterm,
            "final": plan.remaining.final,
        },
        "pending": list(plan.pending),
        "predicted": {
            "value": num(plan.predicted.value),
            "midterm": plan.predicted.midterm,
            "final": plan.predicted.final,
        },
        "targets": [_target(t) for t in plan.targets],
        "assumptions": list(plan.assumptions),
        "what_if": [{"type": m.type, "value": m.value} for m in what_if],
    }
