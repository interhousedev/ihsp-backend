"""Show a subject group (or subgroup) to its teacher (UF-STF-06)."""

import datetime as dt
from uuid import UUID

from app.modules.academic.application.teaching.access import taught_group
from app.modules.academic.application.teaching.views import (
    RosterStudent,
    TeachingGroupView,
)
from app.shared.actor import Actor
from app.shared.clock import Clock, local_today
from app.shared.contracts.academic import ScheduleQueries, StudentRef
from app.shared.contracts.identity import IdentityDirectory

UNKNOWN_NAME = "?"
TIMETABLE_DAYS = 28  # this week and the next three


async def roster_rows(
    identity: IdentityDirectory, students: list[StudentRef]
) -> list[RosterStudent]:
    """The students with their names, sorted by last and first name."""
    users = await identity.get_users([s.user_id for s in students])
    rows = []
    for student in students:
        user = users.get(student.user_id)
        rows.append(
            RosterStudent(
                user_id=student.user_id,
                first_name=user.first_name if user else UNKNOWN_NAME,
                last_name=user.last_name if user else UNKNOWN_NAME,
                subgroup=student.subgroup,
            )
        )
    rows.sort(key=lambda r: (r.last_name.casefold(), r.first_name.casefold()))
    return rows


class GetTeachingGroup:
    """The students of a subject group and its lessons of this and coming weeks."""

    def __init__(
        self, *, schedule: ScheduleQueries, identity: IdentityDirectory, clock: Clock
    ) -> None:
        """Store the collaborators."""
        self.schedule = schedule
        self.identity = identity
        self.clock = clock

    async def execute(
        self, actor: Actor, subject_id: UUID, group_id: UUID, subgroup: int | None
    ) -> TeachingGroupView:
        """Return the group; 403 when the caller does not teach it the subject."""
        today = local_today(self.clock)
        group = await taught_group(
            self.schedule, actor, subject_id, group_id, subgroup, today
        )
        monday = today - dt.timedelta(days=today.weekday())
        end = monday + dt.timedelta(days=TIMETABLE_DAYS)
        return TeachingGroupView(
            subject_id=subject_id,
            subject_name=group.subject_name,
            group_id=group_id,
            group_name=group.group_name,
            subgroup=subgroup,
            subgroups=tuple(sorted(s for s in group.scope if s is not None)),
            students=await roster_rows(self.identity, group.students),
            lessons=[x for x in group.lessons if monday <= x.date < end],
        )
