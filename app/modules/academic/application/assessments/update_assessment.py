"""Staff edit, confirm or dismiss a control (and the EMIS suggestions)."""

from typing import Any
from uuid import UUID

from app.modules.academic.application.assessments.access import ensure_may_manage
from app.modules.academic.application.assessments.ports.unit_of_work import (
    AssessmentsUowFactory,
)
from app.modules.academic.application.assessments.validation import check_references
from app.modules.academic.application.assessments.views import (
    build_view,
    caller_locale,
)
from app.modules.academic.domain.assessments.edit import AssessmentPatch, apply_patch
from app.modules.academic.domain.assessments.errors import AssessmentNotFoundError
from app.shared.actor import Actor
from app.shared.clock import Clock, local_today
from app.shared.contracts.identity import IdentityDirectory
from app.shared.notifications import AuditDraft


class UpdateAssessment:
    """Applies a patch; changing a tentative control confirms it."""

    def __init__(
        self,
        *,
        uow_factory: AssessmentsUowFactory,
        identity: IdentityDirectory,
        clock: Clock,
    ) -> None:
        """Store collaborators."""
        self._uow_factory = uow_factory
        self._identity = identity
        self._clock = clock

    async def execute(
        self, actor: Actor, assessment_id: UUID, patch: AssessmentPatch
    ) -> dict[str, Any]:
        """Return the changed `StaffAssessmentItem`."""
        today = local_today(self._clock)
        locale = await caller_locale(self._identity, actor.user_id)
        async with self._uow_factory() as uow:
            current = await uow.assessments.get(assessment_id)
            if current is None:
                raise AssessmentNotFoundError()
            await ensure_may_manage(
                uow.reader, actor, current.subject_id, current.audience, today
            )
            edited = apply_patch(current, patch, await uow.reader.terms())
            if (edited.subject_id, edited.audience, edited.lesson_id) != (
                current.subject_id,
                current.audience,
                current.lesson_id,
            ):
                await ensure_may_manage(
                    uow.reader, actor, edited.subject_id, edited.audience, today
                )
                await check_references(
                    uow.reader,
                    subject_id=edited.subject_id,
                    audience=edited.audience,
                    lesson_id=edited.lesson_id,
                )
            saved = await uow.assessments.save(edited)
            uow.audit(
                AuditDraft(
                    type="assessment.updated",
                    actor_id=actor.user_id,
                    metadata={
                        "assessment_id": str(saved.id),
                        "from_status": current.status,
                        "status": saved.status,
                    },
                )
            )
            await uow.commit()
            view = await build_view(
                uow.reader,
                self._identity,
                [saved],
                locale=locale,
                today=today,
                staff=True,
            )
        return view.staff_item(saved)
