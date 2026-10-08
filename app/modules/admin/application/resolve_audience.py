"""Turn an audience into the set of active user IDs (ADM-11)."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.admin.domain.audience import Audience
from app.shared.actor import Role
from app.shared.contracts.academic import ScheduleQueries
from app.shared.contracts.identity import IdentityDirectory, UserStatus

ALL_ROLES = (Role.STUDENT, Role.TEACHER, Role.ADMIN, Role.LMS_ADMIN)
CHUNK = 500


class ResolveAudience:
    """Union of everyone / roles / groups / semesters, active users only."""

    def __init__(self, identity: IdentityDirectory, schedule: ScheduleQueries) -> None:
        """Store the directories used to find users."""
        self.identity = identity
        self.schedule = schedule

    async def execute(self, audience: Audience) -> set[UUID]:
        """Return the IDs of active users the audience selects."""
        found: set[UUID] = set()
        if audience.everyone:
            found.update(await self.identity.user_ids_with_roles(ALL_ROLES))
        else:
            if audience.roles:
                found.update(await self.identity.user_ids_with_roles(audience.roles))
            if audience.group_ids:
                found.update(await self.schedule.group_user_ids(audience.group_ids))
            if audience.semesters:
                found.update(await self.schedule.group_user_ids((), audience.semesters))
        return await self._active(sorted(found, key=str))

    async def _active(self, user_ids: Sequence[UUID]) -> set[UUID]:
        active: set[UUID] = set()
        for start in range(0, len(user_ids), CHUNK):
            users = await self.identity.get_users(user_ids[start : start + CHUNK])
            active.update(
                uid for uid, user in users.items() if user.status == UserStatus.ACTIVE
            )
        return active
