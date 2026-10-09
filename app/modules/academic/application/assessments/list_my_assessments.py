"""The student's exam calendar: controls of their group and subgroup."""

import datetime as dt
from typing import Any
from uuid import UUID

from app.modules.academic.application.assessments.ports.repositories import (
    VISIBLE,
    AssessmentQuery,
)
from app.modules.academic.application.assessments.ports.unit_of_work import (
    AssessmentsUowFactory,
)
from app.modules.academic.application.assessments.undated import undated_for_groups
from app.modules.academic.application.assessments.views import (
    build_view,
    caller_locale,
)
from app.modules.academic.domain import audience as audience_keys
from app.modules.academic.domain.marks.errors import StudentNotFoundError
from app.shared.actor import Actor
from app.shared.clock import Clock, local_today
from app.shared.contracts.identity import IdentityDirectory


class ListMyAssessments:
    """Builds `AssessmentItem[]` for the calling student."""

    def __init__(
        self,
        *,
        uow_factory: AssessmentsUowFactory,
        identity: IdentityDirectory,
        clock: Clock,
    ) -> None:
        """Store collaborators."""
        self._uow_factory = uow_factory
        self._identity = identity
        self._clock = clock

    async def execute(
        self,
        actor: Actor,
        *,
        since: dt.date | None = None,
        until: dt.date | None = None,
        subject_id: UUID | None = None,
    ) -> list[dict[str, Any]]:
        """Return planned and tentative controls, soonest first.

        A control week of the term that a curriculum subject has no date for is
        listed too, dated by the week (``has_date`` false).
        """
        today = local_today(self._clock)
        locale = await caller_locale(self._identity, actor.user_id)
        async with self._uow_factory() as uow:
            student = await uow.reader.student(actor.user_id)
            if student is None:
                raise StudentNotFoundError()
            rows = await uow.assessments.find(
                AssessmentQuery(
                    since=since,
                    until=until,
                    subject_id=subject_id,
                    audience=audience_keys.student_keys(
                        student.group_id, student.subgroup
                    ),
                    statuses=VISIBLE,
                )
            )
            subjects = [
                s
                for s in await uow.reader.curriculum(student.group_id)
                if subject_id in (None, s)
            ]
            undated = await undated_for_groups(
                uow.reader,
                uow.assessments,
                {student.group_id: subjects},
                since=since,
                until=until,
            )
            view = await build_view(
                uow.reader,
                self._identity,
                rows,
                locale=locale,
                today=today,
                staff=False,
                extra_subjects=subjects,
            )
        items = [view.item(a) for a in rows] + [view.undated_item(c) for c in undated]
        return sorted(items, key=lambda item: item["date"])  # stable: dated first
