"""Staff cancel a control or dismiss an EMIS suggestion."""

from dataclasses import replace
from uuid import UUID

from app.modules.academic.application.assessments.access import ensure_may_manage
from app.modules.academic.application.assessments.ports.unit_of_work import (
    AssessmentsUowFactory,
)
from app.modules.academic.domain.assessments.errors import AssessmentNotFoundError
from app.shared.actor import Actor
from app.shared.clock import Clock, local_today
from app.shared.notifications import AuditDraft


class DeleteAssessment:
    """Marks a control cancelled; the row stays, so a dismissed suggestion stays so."""

    def __init__(self, *, uow_factory: AssessmentsUowFactory, clock: Clock) -> None:
        """Store collaborators."""
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, actor: Actor, assessment_id: UUID) -> None:
        """Cancel the control; cancelling twice is not an error."""
        today = local_today(self._clock)
        async with self._uow_factory() as uow:
            current = await uow.assessments.get(assessment_id)
            if current is None:
                raise AssessmentNotFoundError()
            await ensure_may_manage(
                uow.reader, actor, current.subject_id, current.audience, today
            )
            if current.status == "cancelled":
                return
            await uow.assessments.save(replace(current, status="cancelled"))
            uow.audit(
                AuditDraft(
                    type="assessment.cancelled",
                    actor_id=actor.user_id,
                    metadata={
                        "assessment_id": str(current.id),
                        "from_status": current.status,
                    },
                )
            )
            await uow.commit()
