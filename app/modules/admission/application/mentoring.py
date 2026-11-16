"""Mentoring switches: each party sets only their own side (both are required)."""

from dataclasses import dataclass

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.domain.errors import AdmissionForbiddenError
from app.modules.admission.ports.repositories import AuditEvent
from app.modules.admission.ports.unit_of_work import UowFactory

MENTEE_CHANGED = "mentoring.mentee_opt_in_changed"
MENTOR_CHANGED = "mentoring.mentor_opt_in_changed"


@dataclass(frozen=True, slots=True)
class MentoringState:
    """The caller's switches and how many mentor assignments they hold."""

    mentee_opt_in: bool
    mentor_opt_in: bool
    mentor_assignments: int


class MentoringService:
    """Reads and sets the two mentoring opt-ins of the caller."""

    def __init__(self, uow_factory: UowFactory) -> None:
        """Keep the unit of work factory."""
        self._uow = uow_factory

    @staticmethod
    def _mentor_assignments(ctx: AdmissionContext) -> int:
        return sum(1 for a in ctx.assignments if a.role.kind == "mentor")

    async def get(self, ctx: AdmissionContext) -> MentoringState:
        """Return the caller's own switches."""
        async with self._uow() as uow:
            mine = (await uow.access.opt_ins([ctx.user_id])).get(ctx.user_id)
        return MentoringState(
            bool(mine and mine.mentee_opt_in),
            bool(mine and mine.mentor_opt_in),
            self._mentor_assignments(ctx),
        )

    async def set_mentee(self, ctx: AdmissionContext, value: bool) -> MentoringState:
        """Let an applicant share their profile with mentors, or stop."""
        if not ctx.admission.is_applicant:
            raise AdmissionForbiddenError(params={"permission": "mentee_opt_in"})
        await self._set(ctx, "mentee_opt_in", value, MENTEE_CHANGED)
        return await self.get(ctx)

    async def set_mentor(self, ctx: AdmissionContext, value: bool) -> MentoringState:
        """Let a mentor accept mentorship, or stop; needs a mentor assignment."""
        if value and not self._mentor_assignments(ctx):
            raise AdmissionForbiddenError(params={"permission": "mentor_opt_in"})
        await self._set(ctx, "mentor_opt_in", value, MENTOR_CHANGED)
        return await self.get(ctx)

    async def _set(
        self, ctx: AdmissionContext, field: str, value: bool, action: str
    ) -> None:
        async with self._uow() as uow:
            await uow.access.set_opt_in(ctx.user_id, field, value)
            uow.access.audit(
                AuditEvent(
                    action=action,
                    actor_id=ctx.user_id,
                    student_id=ctx.user_id,
                    meta={"value": value},
                )
            )
            await uow.commit()
