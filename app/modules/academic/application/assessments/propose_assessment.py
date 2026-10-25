"""A head student suggests a date for a control of their group."""

import datetime as dt
from typing import Any

from app.modules.academic.application.assessments.inputs import ProposalInput
from app.modules.academic.application.assessments.ports.repositories import (
    ANY_STATUS,
    AssessmentQuery,
)
from app.modules.academic.application.assessments.ports.unit_of_work import (
    AssessmentsUowFactory,
)
from app.modules.academic.application.assessments.validation import check_references
from app.modules.academic.application.assessments.views import (
    build_view,
    caller_locale,
)
from app.modules.academic.domain import audience as audience_keys
from app.modules.academic.domain.assessments.edit import (
    NOTE_MAX,
    ROOM_MAX,
    check_starts_at,
    clean_optional,
    clean_title,
    resolve_control,
)
from app.modules.academic.domain.assessments.errors import (
    AssessmentExistsError,
    NotHeadStudentError,
)
from app.modules.academic.domain.assessments.records import NewAssessment
from app.modules.academic.domain.assessments.rules import (
    SAME_CONTROL_WINDOW_DAYS,
    initial_status,
    is_duplicate,
)
from app.modules.academic.domain.marks.errors import StudentNotFoundError
from app.shared.actor import Actor
from app.shared.clock import Clock, local_today
from app.shared.contracts.identity import IdentityDirectory
from app.shared.notifications import AuditDraft


class ProposeAssessment:
    """Stores a tentative control; a teacher or Administration confirms it."""

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

    async def execute(self, actor: Actor, data: ProposalInput) -> dict[str, Any]:
        """Return the new `AssessmentItem`; only the group's head student may call."""
        title = clean_title(data.title)
        room = clean_optional(data.room, "room", ROOM_MAX)
        note = clean_optional(data.note, "note", NOTE_MAX)
        check_starts_at(data.date, data.starts_at)
        today = local_today(self._clock)
        locale = await caller_locale(self._identity, actor.user_id)
        async with self._uow_factory() as uow:
            student = await uow.reader.student(actor.user_id)
            if student is None:
                raise StudentNotFoundError()
            if await uow.reader.head_student_of(student.group_id) != actor.user_id:
                raise NotHeadStudentError()
            audience = (audience_keys.key(student.group_id, None),)
            await check_references(
                uow.reader,
                subject_id=data.subject_id,
                audience=audience,
                lesson_id=None,
            )
            new = NewAssessment(
                subject_id=data.subject_id,
                audience=audience,
                kind=data.kind,
                title=title,
                date=data.date,
                lesson_id=None,
                starts_at=data.starts_at,
                room=room,
                status=initial_status("head_student"),
                source="head_student",
                note=note,
                created_by=actor.user_id,
                control=resolve_control(
                    data.kind, data.date, await uow.reader.terms(), data.control
                ),
            )
            window = dt.timedelta(days=SAME_CONTROL_WINDOW_DAYS)
            known = await uow.assessments.find(
                AssessmentQuery(
                    since=data.date - window,
                    until=data.date + window,
                    subject_id=data.subject_id,
                    group_id=student.group_id,
                    statuses=ANY_STATUS,
                )
            )
            if any(is_duplicate(new, other) for other in known):
                raise AssessmentExistsError()
            created = await uow.assessments.add(new)
            uow.audit(
                AuditDraft(
                    type="assessment.proposed",
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
                staff=False,
            )
        return view.item(created)
