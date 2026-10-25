"""Use case: the student profile of Administration, everything in one place (ADM-3)."""

from uuid import UUID

from app.interfaces.http.v1.composition.application.dates import week_bounds
from app.interfaces.http.v1.composition.errors import StudentNotFoundError
from app.interfaces.http.v1.composition.ports import (
    AccountViews,
    JsonObject,
    StudentViews,
)
from app.shared.actor import Actor, Role
from app.shared.clock import Clock, local_today
from app.shared.contracts.academic import ScheduleQueries
from app.shared.contracts.identity import IdentityDirectory


class BuildStudent360:
    """Profile, week timetable, grades, attendance, Telegram, sessions and audit."""

    def __init__(
        self,
        *,
        identity: IdentityDirectory,
        schedule: ScheduleQueries,
        students: StudentViews,
        accounts: AccountViews,
        clock: Clock,
    ) -> None:
        """Store the collaborators."""
        self.identity = identity
        self.schedule = schedule
        self.students = students
        self.accounts = accounts
        self.clock = clock

    async def execute(
        self, actor: Actor, user_id: UUID, *, ip: str | None, user_agent: str | None
    ) -> JsonObject:
        """Return `Student360`; opening it is audited as `student.viewed`."""
        actor.require(Role.ADMIN)
        user = await self.identity.get_user(user_id)
        if user is None or await self.schedule.get_student(user_id) is None:
            raise StudentNotFoundError(support_details=str(user_id))
        start, end = week_bounds(local_today(self.clock))
        profile = await self.students.profile(user_id)
        timetable = await self.students.timetable(user_id, start, end)
        grades = await self.students.grades(user_id)
        attendance = await self.students.attendance(user_id)
        # The identity use case behind this port records `student.viewed` itself.
        account = await self.accounts.account(
            actor, user_id, ip=ip, user_agent=user_agent
        )
        return {
            "profile": {
                **profile,
                "status": user.status.value,
                "roles": sorted(role.value for role in user.roles),
            },
            "timetable_week": timetable,
            "grades": grades,
            "attendance": attendance,
            "telegram": account.get("telegram", []),
            "sessions": account.get("sessions", []),
            "audit": account.get("recent_audit", []),
        }
