"""Suggest controls from EMIS lessons marked as a midterm or a final.

The lessons come from the schedule's public ``ScheduleQueries.emis_control_lessons``.
EMIS control weeks are right, but the data is filled in late and many teachers have
no plan there. A control lesson inside a week Administration set for the term is
trusted (``planned``); one outside every week only hints (``tentative``) until a
teacher or Administration confirms, edits or dismisses it. A suggestion first read
outside any week becomes ``planned`` when a week later covers it.

Only the *kind* of an EMIS lesson is trusted. Its topic (and files) are not, so an
EMIS-sourced topic never becomes the title of a control.
"""

import datetime as dt
from collections.abc import Sequence

from app.modules.academic.application.assessments.ports.repositories import (
    ANY_STATUS,
    AssessmentQuery,
)
from app.modules.academic.application.assessments.ports.unit_of_work import (
    AssessmentsUowFactory,
)
from app.modules.academic.domain.assessments.records import LessonCandidate
from app.modules.academic.domain.assessments.rules import SAME_CONTROL_WINDOW_DAYS
from app.modules.academic.domain.assessments.suggestions import (
    promote_inside_weeks,
    suggestions_from_lessons,
)
from app.shared.clock import Clock, local_today
from app.shared.contracts.academic import LessonRef, ScheduleQueries

LOOKBACK_DAYS = 14
HORIZON_DAYS = 120


class GenerateTentativeAssessments:
    """Creates the controls EMIS lessons suggest, once each."""

    def __init__(
        self,
        *,
        uow_factory: AssessmentsUowFactory,
        schedule: ScheduleQueries,
        clock: Clock,
    ) -> None:
        """Store collaborators."""
        self._uow_factory = uow_factory
        self._schedule = schedule
        self._clock = clock

    async def execute(self) -> dict[str, int]:
        """Return the exam lessons seen, controls created and suggestions confirmed."""
        today = local_today(self._clock)
        since = today - dt.timedelta(days=LOOKBACK_DAYS)
        until = today + dt.timedelta(days=HORIZON_DAYS)
        margin = dt.timedelta(days=SAME_CONTROL_WINDOW_DAYS)
        async with self._uow_factory() as uow:
            terms = await uow.reader.terms()
            group_ids = await uow.reader.active_group_ids()
            lessons = _candidates(
                await self._schedule.emis_control_lessons(group_ids, since, until)
            )
            existing = await uow.assessments.find(
                AssessmentQuery(
                    since=since - margin,
                    until=until + margin,
                    statuses=ANY_STATUS,
                    limit=20000,
                )
            )
            promoted = promote_inside_weeks(existing, terms)
            for assessment in promoted:
                await uow.assessments.save(assessment)
            promoted_ids = {a.id for a in promoted}
            known = [next((p for p in promoted if p.id == a.id), a) for a in existing]
            fresh = suggestions_from_lessons(lessons, known, terms)
            for new in fresh:
                await uow.assessments.add(new)
            await uow.commit()
        return {
            "lessons": len(lessons),
            "created": len(fresh),
            "confirmed": len(promoted_ids),
        }


def _candidates(refs: Sequence[LessonRef]) -> list[LessonCandidate]:
    """Return the scheduled midterm and final lessons as suggestion candidates.

    The schedule already answers only those; the check keeps a contract that returns
    more from creating controls out of lectures.
    """
    return [
        LessonCandidate(
            lesson_id=ref.id,
            subject_id=ref.subject_id,
            audience=ref.audience,
            date=ref.date,
            starts_at=ref.starts_at,
            kind=ref.kind,
            topic=None if ref.topic_source == "emis" else ref.topic,
            room=ref.room_name,
        )
        for ref in refs
        if ref.kind in ("midterm", "final") and ref.status == "scheduled"
    ]
