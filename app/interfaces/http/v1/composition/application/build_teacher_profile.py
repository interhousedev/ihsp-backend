"""Use case: the teacher profile of Administration (ADM-4)."""

from uuid import UUID

from app.interfaces.http.v1.composition.application.dates import (
    missing_attendance_window,
    week_bounds,
)
from app.interfaces.http.v1.composition.errors import TeacherNotFoundError
from app.interfaces.http.v1.composition.ports import (
    AccountViews,
    JsonObject,
    TeacherViews,
)
from app.shared.actor import Actor, Role
from app.shared.clock import Clock, local_today
from app.shared.contracts.identity import IdentityDirectory


class BuildTeacherProfile:
    """The account, week timetable, lessons without attendance and curated groups."""

    def __init__(
        self,
        *,
        identity: IdentityDirectory,
        teachers: TeacherViews,
        accounts: AccountViews,
        clock: Clock,
    ) -> None:
        """Store the collaborators."""
        self.identity = identity
        self.teachers = teachers
        self.accounts = accounts
        self.clock = clock

    async def execute(
        self, actor: Actor, user_id: UUID, *, ip: str | None, user_agent: str | None
    ) -> JsonObject:
        """Return `TeacherProfile`."""
        actor.require(Role.ADMIN)
        user = await self.identity.get_user(user_id)
        if user is None or Role.TEACHER not in user.roles:
            raise TeacherNotFoundError(support_details=str(user_id))
        today = local_today(self.clock)
        week_start, week_end = week_bounds(today)
        missing_start, missing_end = missing_attendance_window(today)
        account = await self.accounts.account(
            actor, user_id, ip=ip, user_agent=user_agent
        )
        return {
            "user": account,
            "timetable_week": await self.teachers.timetable(
                user_id, week_start, week_end
            ),
            "missing_attendance": await self.teachers.missing_attendance(
                user_id, missing_start, missing_end
            ),
            "curated_groups": await self.teachers.curated_groups(user_id),
        }
