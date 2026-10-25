"""Remind students 7, 3 and 1 days before a confirmed control (notify outbox).

A control counts down to the subject's date when it has one, else to the start of the
control week Administration set. Only ``planned`` controls are reminded: a date nobody
confirmed may be wrong, and a wrong reminder costs more trust than a missing one.
"""

import datetime as dt
from dataclasses import dataclass
from uuid import UUID

from app.modules.academic.application.assessments.ports.repositories import (
    AssessmentQuery,
)
from app.modules.academic.application.assessments.ports.unit_of_work import (
    AssessmentsUnitOfWork,
    AssessmentsUowFactory,
)
from app.modules.academic.application.assessments.undated import undated_for_groups
from app.modules.academic.domain.assessments.records import Assessment
from app.modules.academic.domain.assessments.rules import (
    REMINDER_OFFSETS,
    days_left,
    reminder_offset,
)
from app.modules.academic.domain.marks.names import localized
from app.shared.clock import Clock, local_today
from app.shared.contracts.identity import IdentityDirectory
from app.shared.notifications import NotificationDraft, NotificationType

Payload = dict[str, object]


@dataclass(frozen=True, slots=True)
class _Due:
    """One control that is reminded today, with whom and what to say."""

    assessment_id: UUID
    subject_id: UUID
    audience: tuple[str, ...]
    offset: int
    payload: Payload


class SendAssessmentReminders:
    """Queues `assessment_reminder` notifications; a rerun adds nothing new."""

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

    async def execute(self) -> dict[str, int]:
        """Return the controls reminded and the notifications queued."""
        today = local_today(self._clock)
        async with self._uow_factory() as uow:
            due = await self._due(uow, today)
            drafts = await self._drafts(uow, due)
            if drafts:
                uow.notify(*drafts)
                await uow.commit()
        return {"assessments": len(due), "notifications": len(drafts)}

    async def _due(self, uow: AssessmentsUnitOfWork, today: dt.date) -> list[_Due]:
        first = today + dt.timedelta(days=min(REMINDER_OFFSETS))
        last = today + dt.timedelta(days=max(REMINDER_OFFSETS))
        stored = await uow.assessments.find(
            AssessmentQuery(since=first, until=last, statuses=("planned",), limit=20000)
        )
        due = [
            _stored(a, offset)
            for a in stored
            if (offset := reminder_offset(a, today)) is not None
        ]
        # A week that starts within seven days and has no subject date yet.
        undated = await undated_for_groups(
            uow.reader,
            uow.assessments,
            await uow.reader.curricula(),
            since=first,
            until=last,
        )
        for c in undated:
            offset = days_left(c.period.start, today)
            if offset in REMINDER_OFFSETS:
                due.append(
                    _Due(
                        c.id,
                        c.subject_id,
                        c.audience,
                        offset,
                        {
                            "assessment_id": str(c.id),
                            "kind": c.kind,
                            "control": c.control,
                            "title": "",
                            "date": c.period.start.isoformat(),
                            "period_end": c.period.end.isoformat(),
                            "days_left": offset,
                            "starts_at": None,
                            "room": None,
                        },
                    )
                )
        return due

    async def _drafts(
        self, uow: AssessmentsUnitOfWork, due: list[_Due]
    ) -> list[NotificationDraft]:
        if not due:
            return []
        subjects = await uow.reader.subjects({d.subject_id for d in due})
        recipients = {
            d.assessment_id: await uow.reader.user_ids_for_audience(d.audience)
            for d in due
        }
        everyone = sorted({u for ids in recipients.values() for u in ids}, key=str)
        users = await self._identity.get_users(everyone) if everyone else {}
        drafts: list[NotificationDraft] = []
        for d in due:
            info = subjects.get(d.subject_id)
            for user_id in recipients[d.assessment_id]:
                locale = users[user_id].locale if user_id in users else "ru"
                name = "" if info is None else localized(info.name, locale)
                drafts.append(
                    NotificationDraft(
                        user_id=user_id,
                        type=NotificationType.ASSESSMENT_REMINDER,
                        payload={**d.payload, "subject_name": name},
                        dedupe_key=_dedupe_key(user_id, d.assessment_id, d.offset),
                    )
                )
        return drafts


def _stored(a: Assessment, offset: int) -> _Due:
    return _Due(
        a.id,
        a.subject_id,
        a.audience,
        offset,
        {
            "assessment_id": str(a.id),
            "kind": a.kind,
            "control": a.control,
            "title": a.title,
            "date": a.date.isoformat(),
            "period_end": None,
            "days_left": offset,
            "starts_at": None if a.starts_at is None else a.starts_at.isoformat(),
            "room": a.room,
        },
    )


def _dedupe_key(user_id: UUID, assessment_id: UUID, offset: int) -> str:
    return f"assessment_reminder:{user_id}:{assessment_id}:{offset}"
