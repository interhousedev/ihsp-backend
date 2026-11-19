"""Self-reported application outcomes and their aggregate."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from app.modules.admission.application.access import VIEWED, AccessPolicy
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.staff import display_name
from app.modules.admission.domain.errors import (
    AdmissionConflictError,
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    InvalidAnswerError,
)
from app.modules.admission.domain.institution_brand import InstitutionBrand
from app.modules.admission.domain.outcomes import (
    MAX_CYCLE,
    MIN_CYCLE,
    OUTCOME_PLANS,
    OUTCOME_STATUSES,
    Outcome,
    OutcomeStatus,
    OutcomeTally,
    aggregate,
    revealed_students,
)
from app.modules.admission.ports.repositories import AuditEvent
from app.modules.admission.ports.unit_of_work import UowFactory
from app.shared.actor import Role
from app.shared.contracts.identity import IdentityDirectory
from app.shared.ids import new_id


@dataclass(frozen=True, slots=True)
class OutcomeSummary:
    """Tallies per institution and cycle, with the institutions' names and logos."""

    tallies: list[OutcomeTally]
    institutions: dict[UUID, InstitutionBrand]
    reported: int
    accepted: int


def _check(*, status: str, plan: str, cycle: int | None = None) -> None:
    if status not in OUTCOME_STATUSES:
        raise InvalidAnswerError(params={"field": "status"})
    if plan not in OUTCOME_PLANS:
        raise InvalidAnswerError(params={"field": "plan"})
    if cycle is not None and not MIN_CYCLE <= cycle <= MAX_CYCLE:
        raise InvalidAnswerError(params={"field": "cycle"})


class OutcomeService:
    """A student's own reports and the shared, privacy-aware aggregate."""

    def __init__(
        self,
        uow_factory: UowFactory,
        access: AccessPolicy,
        identity: IdentityDirectory | None = None,
    ) -> None:
        """Wire the unit of work, the access policy and the name directory."""
        self._uow = uow_factory
        self._access = access
        self._identity = identity

    @staticmethod
    def _applicant(ctx: AdmissionContext) -> None:
        if not ctx.admission.is_applicant:
            raise AdmissionForbiddenError()

    async def mine(self, ctx: AdmissionContext) -> list[Outcome]:
        """The caller's reports."""
        self._applicant(ctx)
        async with self._uow() as uow:
            return await uow.outcomes.list_for(ctx.user_id)

    async def create(
        self,
        ctx: AdmissionContext,
        *,
        institution_id: UUID,
        cycle: int,
        plan: str,
        status: str,
        share_name: bool,
    ) -> Outcome:
        """Report an outcome; one per institution and cycle."""
        self._applicant(ctx)
        _check(status=status, plan=plan, cycle=cycle)
        async with self._uow() as uow:
            if institution_id not in await uow.deadlines.institution_names(
                [institution_id]
            ):
                raise AdmissionNotFoundError()
            if await uow.outcomes.find(ctx.user_id, institution_id, cycle):
                raise AdmissionConflictError()
            row = await uow.outcomes.add(
                Outcome(
                    id=new_id(),
                    student_id=ctx.user_id,
                    institution_id=institution_id,
                    cycle=cycle,
                    plan=plan,
                    status=cast(OutcomeStatus, status),
                    share_name=share_name,
                )
            )
            await uow.commit()
            return row

    async def update(
        self,
        ctx: AdmissionContext,
        outcome_id: UUID,
        *,
        lock_version: int,
        plan: str | None = None,
        status: str | None = None,
        share_name: bool | None = None,
    ) -> Outcome:
        """Change plan, status or sharing of the caller's report."""
        self._applicant(ctx)
        async with self._uow() as uow:
            current = await uow.outcomes.get(outcome_id)
            if current is None or current.student_id != ctx.user_id:
                raise AdmissionNotFoundError()
            changed = dataclasses.replace(
                current,
                plan=plan if plan is not None else current.plan,
                status=cast(OutcomeStatus, status or current.status),
                share_name=(current.share_name if share_name is None else share_name),
            )
            _check(status=changed.status, plan=changed.plan)
            saved = await uow.outcomes.save(changed, expected_lock=lock_version)
            await uow.commit()
            return saved

    async def delete(self, ctx: AdmissionContext, outcome_id: UUID) -> None:
        """Remove the caller's report."""
        self._applicant(ctx)
        async with self._uow() as uow:
            current = await uow.outcomes.get(outcome_id)
            if current is None or current.student_id != ctx.user_id:
                raise AdmissionNotFoundError()
            await uow.outcomes.delete(outcome_id)
            await uow.commit()

    async def summary(
        self,
        ctx: AdmissionContext,
        *,
        institution_id: UUID | None = None,
        cycle: int | None = None,
    ) -> OutcomeSummary:
        """Tally where students applied, naming only revealable students.

        Names: those who opted in, plus every student the caller reaches
        (admin, or a live assignment covering the student; audited).
        """
        if not (ctx.admission.is_staff or ctx.admission.is_applicant):
            raise AdmissionForbiddenError()
        async with self._uow() as uow:
            rows = await uow.outcomes.all(institution_id=institution_id, cycle=cycle)
            institutions = await uow.deadlines.institution_brands(
                {o.institution_id for o in rows}
            )
        ids = revealed_students(rows, reveal_all=False)
        ids |= await self._reachable(ctx, {o.student_id for o in rows} - ids)
        names: dict[UUID, str] = {}
        if ids and self._identity is not None:
            users = await self._identity.get_users(list(ids))
            names = {uid: display_name(ref) for uid, ref in users.items()}
        # `names` holds only revealable students, so every resolved name is listed.
        tallies = aggregate(rows, names, reveal_all=True)
        return OutcomeSummary(
            tallies=tallies,
            institutions=institutions,
            reported=sum(t.reported for t in tallies),
            accepted=sum(t.accepted for t in tallies),
        )

    async def _reachable(self, ctx: AdmissionContext, hidden: set[UUID]) -> set[UUID]:
        """Hidden students the caller may name; each reveal is audited."""
        if not hidden:
            return set()
        if Role.ADMIN in ctx.actor.roles:
            reached = set(hidden)
        elif ctx.admission.is_staff:
            reached = {
                sid
                for sid in hidden
                if ctx.user_id != sid
                and (await self._access.resolve(ctx, sid)).in_scope
            }
        else:
            return set()
        if reached:
            async with self._uow() as uow:
                for sid in sorted(reached):
                    uow.access.audit(
                        AuditEvent(
                            action=VIEWED,
                            actor_id=ctx.user_id,
                            student_id=sid,
                            object_type="outcome_summary",
                            meta={"reveal": "name"},
                        )
                    )
                await uow.commit()
        return reached
