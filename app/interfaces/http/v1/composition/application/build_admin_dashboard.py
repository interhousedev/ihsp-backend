"""Use case: the Administration dashboard (ADM-2)."""

import datetime as dt
from collections import Counter

from app.interfaces.http.v1.composition.application.dates import (
    missing_attendance_window,
)
from app.interfaces.http.v1.composition.application.views import (
    load_users,
    person_ref,
)
from app.interfaces.http.v1.composition.ports import (
    BroadcastViews,
    JsonObject,
    ScheduleOverview,
    SyncViews,
)
from app.shared.actor import Actor, Role
from app.shared.clock import Clock, local_today
from app.shared.contracts.academic import ClassworkQueries
from app.shared.contracts.identity import IdentityDirectory, UserStatus

SCHEDULED_BROADCASTS_LIMIT = 20


class BuildAdminDashboard:
    """Today's lessons, missing attendance, EMIS sync state and scheduled broadcasts."""

    def __init__(
        self,
        *,
        identity: IdentityDirectory,
        classwork: ClassworkQueries,
        overview: ScheduleOverview,
        sync: SyncViews,
        broadcasts: BroadcastViews,
        clock: Clock,
    ) -> None:
        """Store the collaborators."""
        self.identity = identity
        self.classwork = classwork
        self.overview = overview
        self.sync = sync
        self.broadcasts = broadcasts
        self.clock = clock

    async def execute(self, actor: Actor) -> JsonObject:
        """Return `AdminDashboard`."""
        actor.require(Role.ADMIN)
        today = local_today(self.clock)
        counts = await self.overview.day_counts(actor, today)
        return {
            "today": {
                "lessons": counts.lessons,
                "cancelled": counts.cancelled,
                "teacher_needed": counts.teacher_needed,
            },
            "missing_attendance": await self._missing_attendance(today),
            "sync": {
                "last_run": await self.sync.last_sync_run(actor),
                "needs_reauth": await self._needs_reauth(),
            },
            "scheduled_broadcasts": await self.broadcasts.scheduled(
                actor, SCHEDULED_BROADCASTS_LIMIT
            ),
        }

    async def _missing_attendance(self, today: dt.date) -> list[JsonObject]:
        """Count finished lessons without attendance per teacher, worst first."""
        start, end = missing_attendance_window(today)
        refs = await self.classwork.missing_attendance(None, start, end)
        per_teacher = Counter(r.teacher_id for r in refs if r.teacher_id is not None)
        teachers = await load_users(self.identity, per_teacher)
        ranked = sorted(
            (
                (-count, user.last_name.casefold(), user.first_name.casefold(), user)
                for teacher_id, count in per_teacher.items()
                if (user := teachers.get(teacher_id)) is not None
            ),
            key=lambda row: row[:3],
        )
        return [{"teacher": person_ref(row[3]), "count": -row[0]} for row in ranked]

    async def _needs_reauth(self) -> int:
        """Count active students whose EMIS password needs updating."""
        student_ids = await self.identity.user_ids_with_roles([Role.STUDENT])
        users = await load_users(self.identity, student_ids)
        return sum(
            1
            for user in users.values()
            if user.status is UserStatus.ACTIVE and user.emis_status == "needs_reauth"
        )
