"""Controls for the staff portal (a teacher's own) and the admin list (all)."""

from typing import Any
from uuid import UUID

from app.modules.academic.application.assessments.inputs import StaffFilters
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
from app.modules.academic.domain.assessments.records import Assessment
from app.shared.actor import Actor, Role
from app.shared.clock import Clock, local_today
from app.shared.contracts.identity import IdentityDirectory


class ListStaffAssessments:
    """Builds `StaffAssessmentItem[]`; a teacher sees only what they teach."""

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
        self, actor: Actor, filters: StaffFilters, *, everything: bool = False
    ) -> list[dict[str, Any]]:
        """Return the controls matching the filters, oldest date first.

        ``everything`` is for the admin list: it needs the admin role and skips the
        teacher scope. Without a status filter cancelled controls are left out.
        With ``filters.undated`` the control weeks that have no date for a subject
        are listed too (not with a status, source or kind other than theirs).
        """
        today = local_today(self._clock)
        locale = await caller_locale(self._identity, actor.user_id)
        see_all = actor.has(Role.ADMIN) and (everything or not actor.has(Role.TEACHER))
        query = AssessmentQuery(
            since=filters.since,
            until=filters.until,
            subject_id=filters.subject_id,
            group_id=filters.group_id,
            kind=filters.kind,
            source=filters.source,
            statuses=VISIBLE if filters.status is None else (filters.status,),
        )
        async with self._uow_factory() as uow:
            rows = await uow.assessments.find(query)
            taught = None
            if not see_all:
                taught = await uow.reader.taught_groups(actor.user_id, today)
                rows = [a for a in rows if _teaches(taught, a)]
            undated = []
            if filters.undated and _may_be_undated(filters):
                curricula = await uow.reader.curricula()
                scoped = _scope(curricula, filters, taught)
                undated = await undated_for_groups(
                    uow.reader,
                    uow.assessments,
                    scoped,
                    since=filters.since,
                    until=filters.until,
                )
                undated = [c for c in undated if filters.kind in (None, c.kind)]
            view = await build_view(
                uow.reader,
                self._identity,
                rows,
                locale=locale,
                today=today,
                staff=True,
                extra_subjects={c.subject_id for c in undated},
                extra_groups={c.group_id for c in undated},
            )
        items = [view.staff_item(a) for a in rows]
        items += [view.staff_undated_item(c) for c in undated]
        return sorted(items, key=lambda item: item["date"])


def _may_be_undated(filters: StaffFilters) -> bool:
    """An undated week is planned and comes from Administration."""
    return filters.status in (None, "planned") and filters.source in (None, "admin")


def _scope(
    curricula: dict[UUID, tuple[UUID, ...]],
    filters: StaffFilters,
    taught: dict[UUID, set[UUID]] | None,
) -> dict[UUID, list[UUID]]:
    """Return the group -> subjects to look at, narrowed by filters and teacher."""
    scoped: dict[UUID, list[UUID]] = {}
    for group_id, subjects in curricula.items():
        if filters.group_id not in (None, group_id):
            continue
        wanted = [
            s
            for s in subjects
            if filters.subject_id in (None, s)
            and (taught is None or group_id in taught.get(s, set()))
        ]
        if wanted:
            scoped[group_id] = wanted
    return scoped


def _teaches(taught: dict[UUID, set[UUID]], assessment: Assessment) -> bool:
    groups = audience_keys.group_ids(assessment.audience)
    return bool(groups & taught.get(assessment.subject_id, set()))
