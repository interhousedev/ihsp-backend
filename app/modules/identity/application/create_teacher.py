"""POST /v1/admin/teachers: create a teacher account (UF-ADM-02)."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.identity.application.create_staff_account import (
    CreateStaffAccount,
    StaffCreated,
)
from app.modules.identity.application.request_context import RequestContext
from app.shared.actor import Role


@dataclass(frozen=True, slots=True)
class CreateTeacher:
    """A staff account with the teacher role."""

    creator: CreateStaffAccount

    async def execute(
        self,
        actor_id: UUID,
        *,
        last_name: str,
        first_name: str,
        middle_name: str | None,
        email: str,
        ctx: RequestContext,
    ) -> StaffCreated:
        """Create the teacher and return the activation link."""
        return await self.creator.execute(
            actor_id=actor_id,
            last_name=last_name,
            first_name=first_name,
            middle_name=middle_name,
            email=email,
            roles=[Role.TEACHER],
            ctx=ctx,
        )
