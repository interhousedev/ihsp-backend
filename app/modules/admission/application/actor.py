"""Who the caller is in the admission app (§4.1): computed once per request."""

import datetime as dt
from collections.abc import Collection
from dataclasses import dataclass
from uuid import UUID

from app.modules.admission.domain.access import ActorFacts, Assignment, Entitlement
from app.modules.admission.domain.entitlement import (
    AdmissionActor,
    admission_staff_roles,
    grade_from_group_name,
)
from app.modules.admission.domain.permissions import KIND_ROLE
from app.modules.admission.ports.unit_of_work import UowFactory
from app.shared.actor import Actor, Role
from app.shared.clock import Clock
from app.shared.contracts.academic import AcademicMembership, StudentRef


def effective_entitlement(
    stored: Entitlement | None,
    student: StudentRef | None,
    eligible_grades: Collection[int],
    now: dt.datetime,
) -> Entitlement | None:
    """Return the stored entitlement, or the implicit one of an eligible student.

    A lyceum student of an eligible grade is entitled without a row; a stored row
    (granted or revoked by an administrator) always wins.
    """
    if stored is not None:
        return stored
    if student is None:
        return None
    if grade_from_group_name(student.group_name) not in eligible_grades:
        return None
    return Entitlement(
        user_id=student.user_id,
        kind="school_student",
        cohort_year=None,
        granted_by=None,
        granted_at=now,
    )


@dataclass(frozen=True, slots=True)
class AdmissionContext:
    """The caller with every fact the access policy needs."""

    actor: Actor
    admission: AdmissionActor
    grade: int | None
    group_ids: frozenset[UUID]
    assignments: tuple[Assignment, ...]
    mentor_opt_in: bool

    @property
    def user_id(self) -> UUID:
        """Return the caller's user id."""
        return self.actor.user_id

    def facts(self) -> ActorFacts:
        """Return the actor side of `resolve`."""
        return ActorFacts(
            user_id=self.actor.user_id,
            active=True,
            roles=self.actor.roles,
            mentor_opt_in=self.mentor_opt_in,
            assignments=self.assignments,
        )


def can_edit_settings(ctx: AdmissionContext, now: dt.datetime) -> bool:
    """Admission settings: an administrator or a live counselor."""
    if Role.ADMIN in ctx.actor.roles:
        return True
    return any(
        a.role.kind == "counselor"
        and a.active_at(now)
        and KIND_ROLE["counselor"] in ctx.actor.roles
        for a in ctx.assignments
    )


class ResolveAdmissionActor:
    """Builds the AdmissionContext of a caller."""

    def __init__(
        self,
        uow_factory: UowFactory,
        membership: AcademicMembership,
        clock: Clock,
        eligible_grades: Collection[int],
    ) -> None:
        """Keep the transaction factory, membership, clock and eligible grades."""
        self._uow = uow_factory
        self._membership = membership
        self._clock = clock
        self._grades = frozenset(eligible_grades)

    async def execute(self, actor: Actor) -> AdmissionContext:
        """Read entitlement, assignments and the caller's group."""
        now = self._clock.now()
        student = (
            await self._membership.student(actor.user_id)
            if Role.STUDENT in actor.roles
            else None
        )
        async with self._uow() as uow:
            stored = await uow.access.entitlement(actor.user_id)
            assignments = await uow.access.assignments_for(actor.user_id)
            opt_ins = await uow.access.opt_ins([actor.user_id])
        entitlement = effective_entitlement(stored, student, self._grades, now)
        mine = opt_ins.get(actor.user_id)
        return AdmissionContext(
            actor=actor,
            admission=AdmissionActor(
                user_id=actor.user_id,
                entitlement=entitlement,
                staff_roles=admission_staff_roles(actor.roles),
                student_role=Role.STUDENT in actor.roles,
            ),
            grade=grade_from_group_name(student.group_name) if student else None,
            group_ids=frozenset({student.group_id}) if student else frozenset(),
            assignments=assignments,
            mentor_opt_in=bool(mine and mine.mentor_opt_in),
        )
