"""The access policy every admission read and write goes through (§4.4)."""

from collections.abc import Collection
from dataclasses import dataclass
from uuid import UUID

from app.modules.admission.application.actor import (
    AdmissionContext,
    effective_entitlement,
)
from app.modules.admission.domain.access import (
    Resolution,
    StudentAccessFacts,
    resolve,
)
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
)
from app.modules.admission.domain.permissions import KIND_ROLE, Permission
from app.modules.admission.ports.consent import STAFF_VIEW, PurposeConsents
from app.modules.admission.ports.repositories import AuditEvent
from app.modules.admission.ports.unit_of_work import UowFactory
from app.shared.clock import Clock
from app.shared.contracts.academic import AcademicMembership

VIEWED = "student.viewed"


@dataclass(frozen=True, slots=True)
class StaffScope:
    """Which students a staff member reaches, before consent and opt-in checks."""

    everyone: bool
    group_ids: frozenset[UUID]
    student_ids: frozenset[UUID]

    @property
    def empty(self) -> bool:
        """Return whether the scope reaches nobody."""
        return not (self.everyone or self.group_ids or self.student_ids)


class AccessPolicy:
    """Resolves permissions over a student and records non-owner reads.

    A student outside the caller's scope is reported as not found (404) so that
    existence does not leak; in scope without the permission is 403.
    """

    def __init__(
        self,
        uow_factory: UowFactory,
        membership: AcademicMembership,
        consents: PurposeConsents,
        clock: Clock,
        eligible_grades: Collection[int],
    ) -> None:
        """Keep the collaborators."""
        self._uow = uow_factory
        self._membership = membership
        self._consents = consents
        self._clock = clock
        self._grades = frozenset(eligible_grades)

    async def student_facts(self, student_id: UUID) -> StudentAccessFacts:
        """Read the student side of `resolve`."""
        now = self._clock.now()
        student = await self._membership.student(student_id)
        granted = await self._consents.granted([student_id])
        async with self._uow() as uow:
            stored = await uow.access.entitlement(student_id)
            opt_ins = await uow.access.opt_ins([student_id])
        entitlement = effective_entitlement(stored, student, self._grades, now)
        mine = opt_ins.get(student_id)
        return StudentAccessFacts(
            student_id=student_id,
            group_ids=frozenset({student.group_id}) if student else frozenset(),
            staff_view_consent=STAFF_VIEW in granted.get(student_id, frozenset()),
            mentee_opt_in=bool(mine and mine.mentee_opt_in),
            entitled=entitlement is not None and entitlement.is_applicant,
        )

    async def resolve(self, ctx: AdmissionContext, student_id: UUID) -> Resolution:
        """Return the caller's permissions over the student."""
        facts = await self.student_facts(student_id)
        return resolve(ctx.facts(), facts, self._clock.now())

    async def require(
        self,
        ctx: AdmissionContext,
        student_id: UUID,
        permission: Permission,
        *,
        object_type: str | None = None,
        object_id: UUID | None = None,
    ) -> Resolution:
        """Return the resolution or raise; a non-owner access is audited."""
        resolution = await self.resolve(ctx, student_id)
        if not resolution.in_scope:
            raise AdmissionNotFoundError()
        if permission not in resolution.permissions:
            raise AdmissionForbiddenError(params={"permission": permission.value})
        if not resolution.owner:
            async with self._uow() as uow:
                uow.access.audit(
                    AuditEvent(
                        action=VIEWED,
                        actor_id=ctx.user_id,
                        student_id=student_id,
                        object_type=object_type,
                        object_id=object_id,
                        staff_role_id=self._role_of(ctx, resolution),
                        meta={
                            "permission": permission.value,
                            "limited": resolution.limited,
                        },
                    )
                )
                await uow.commit()
        return resolution

    def scope(self, ctx: AdmissionContext) -> StaffScope:
        """Return the reach of the caller's live assignments (lists, dashboards)."""
        now = self._clock.now()
        everyone = False
        groups: set[UUID] = set()
        students: set[UUID] = set(ctx.helper_of)
        for a in ctx.assignments:
            if (
                not a.active_at(now)
                or KIND_ROLE.get(a.role.kind) not in ctx.actor.roles
            ):
                continue
            if a.scope_kind == "all":
                everyone = True
            elif a.scope_ref is not None:
                (groups if a.scope_kind == "cohort" else students).add(a.scope_ref)
        return StaffScope(everyone, frozenset(groups), frozenset(students))

    async def students_in_scope(self, ctx: AdmissionContext) -> list[UUID] | None:
        """Return the reached student ids, or None when the scope is everyone."""
        scope = self.scope(ctx)
        if scope.everyone:
            return None
        ids = set(scope.student_ids)
        if scope.group_ids:
            ids |= set(await self._membership.students_in_groups(list(scope.group_ids)))
        return sorted(ids)

    @staticmethod
    def _role_of(ctx: AdmissionContext, resolution: Resolution) -> UUID | None:
        """Return the sub-role of the first assignment that granted the access."""
        if not resolution.via:
            return None
        first = resolution.via[0]
        return next((a.role.id for a in ctx.assignments if a.id == first), None)
