"""Staff recipients of a student notification, filtered by real access."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.domain.entitlement import (
    AdmissionActor,
    admission_staff_roles,
)
from app.modules.admission.domain.permissions import Permission
from app.modules.admission.ports.unit_of_work import UowFactory
from app.shared.actor import Actor, Role
from app.shared.contracts.identity import IdentityDirectory


async def permitted_staff(
    identity: IdentityDirectory | None,
    uow_factory: UowFactory,
    access: AccessPolicy,
    roles: Sequence[Role],
    student_id: UUID,
    permission: Permission,
) -> list[UUID]:
    """Return staff holding `roles` whom access resolution lets do `permission`.

    Resolution applies assignments and the student's staff-view consent, so a
    withdrawn consent or a missing assignment keeps the notice away.
    """
    if identity is None:
        return []
    held: dict[UUID, set[Role]] = {}
    for role in roles:
        for user_id in await identity.user_ids_with_roles([role]):
            held.setdefault(user_id, set()).add(role)
    out: list[UUID] = []
    for user_id, user_roles in held.items():
        async with uow_factory() as uow:
            assignments = await uow.access.assignments_for(user_id)
        actor = Actor(user_id, frozenset(user_roles))
        staff_ctx = AdmissionContext(
            actor=actor,
            admission=AdmissionActor(
                user_id=user_id,
                entitlement=None,
                staff_roles=admission_staff_roles(actor.roles),
                has_help_grants=False,
            ),
            grade=None,
            group_ids=frozenset(),
            assignments=assignments,
            helper_of=frozenset(),
            mentor_opt_in=False,
        )
        res = await access.resolve(staff_ctx, student_id)
        if res.in_scope and permission in res.permissions:
            out.append(user_id)
    return out
