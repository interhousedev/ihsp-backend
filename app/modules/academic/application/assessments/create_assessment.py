"""A teacher or Administration plans a control (staff portal, admin portal)."""

from typing import Any

from app.modules.academic.application.assessments.access import ensure_may_manage
from app.modules.academic.application.assessments.inputs import AssessmentInput
from app.modules.academic.application.assessments.ports.unit_of_work import (
    AssessmentsUowFactory,
)
from app.modules.academic.application.assessments.validation import check_references
from app.modules.academic.application.assessments.views import (
    build_view,
    caller_locale,
)
from app.modules.academic.domain.assessments.edit import (
    NOTE_MAX,
    ROOM_MAX,
    check_starts_at,
    clean_optional,
    clean_title,
    normalize_audience,
    resolve_control,
)
from app.modules.academic.domain.assessments.records import (
    AssessmentSource,
    NewAssessment,
)
from app.modules.academic.domain.assessments.rules import initial_status
from app.shared.actor import Actor, Role
from app.shared.clock import Clock, local_today
from app.shared.contracts.identity import IdentityDirectory
from app.shared.notifications import AuditDraft


class CreateAssessment:
    """Stores a planned control for a subject and an audience."""

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

    async def execute(self, actor: Actor, data: AssessmentInput) -> dict[str, Any]:
        """Return the new `StaffAssessmentItem`; a teacher needs to teach the group."""
        audience = normalize_audience(data.audience)
        title = clean_title(data.title)
        room = clean_optional(data.room, "room", ROOM_MAX)
        note = clean_optional(data.note, "note", NOTE_MAX)
        check_starts_at(data.date, data.starts_at)
        today = local_today(self._clock)
        source: AssessmentSource = "admin" if actor.has(Role.ADMIN) else "teacher"
        locale = await caller_locale(self._identity, actor.user_id)
        async with self._uow_factory() as uow:
            await ensure_may_manage(uow.reader, actor, data.subject_id, audience, today)
            await check_references(
                uow.reader,
                subject_id=data.subject_id,
                audience=audience,
                lesson_id=data.lesson_id,
            )
            control = resolve_control(
                data.kind, data.date, await uow.reader.terms(), data.control
            )
            created = await uow.assessments.add(
                NewAssessment(
                    subject_id=data.subject_id,
                    audience=audience,
                    kind=data.kind,
                    title=title,
                    date=data.date,
                    lesson_id=data.lesson_id,
                    starts_at=data.starts_at,
                    room=room,
                    status=initial_status(source),
                    source=source,
                    note=note,
                    created_by=actor.user_id,
                    control=control,
                )
            )
            uow.audit(
                AuditDraft(
                    type="assessment.created",
                    actor_id=actor.user_id,
                    metadata={"assessment_id": str(created.id), "kind": created.kind},
                )
            )
            await uow.commit()
            view = await build_view(
                uow.reader,
                self._identity,
                [created],
                locale=locale,
                today=today,
                staff=True,
            )
        return view.staff_item(created)
