"""Deadline nudges and the result question, sent by the reminder job."""

from __future__ import annotations

from uuid import UUID

from app.modules.admission.domain.documents import ReminderPrefs, shift_out_of_quiet
from app.modules.admission.domain.outcomes import plan_nudges
from app.modules.admission.ports.unit_of_work import UowFactory
from app.shared.clock import Clock
from app.shared.notifications import NotificationDraft, NotificationType


class NudgeService:
    """Asks students about institutions they follow, before and after the deadline."""

    def __init__(self, uow_factory: UowFactory, clock: Clock) -> None:
        """Wire the unit of work and the clock."""
        self._uow = uow_factory
        self._clock = clock

    async def run(self) -> int:
        """Queue due nudges through the notify outbox; return how many."""
        now = self._clock.now()
        queued = 0
        async with self._uow() as uow:
            targets = await uow.outcomes.nudge_targets()
            if not targets:
                return 0
            deadlines = await uow.deadlines.current()
            reported = await uow.outcomes.reported_keys({t.student_id for t in targets})
            nudges = plan_nudges(now, targets, deadlines, reported)
            names = await uow.deadlines.institution_names(
                {n.institution_id for n in nudges}
            )
            prefs_cache: dict[UUID, ReminderPrefs] = {}
            for n in nudges:
                if n.student_id not in prefs_cache:
                    prefs_cache[n.student_id] = await uow.deadlines.prefs(
                        n.student_id
                    ) or ReminderPrefs(n.student_id)
                prefs = prefs_cache[n.student_id]
                if n.kind in ("d30", "d7") and n.offset_days not in prefs.offsets_days:
                    continue
                when = shift_out_of_quiet(now, prefs.quiet_from, prefs.quiet_to)
                uow.notify(
                    NotificationDraft(
                        user_id=n.student_id,
                        type=NotificationType.ADMISSION_DEADLINE_REMINDER,
                        payload={
                            "kind": n.kind,
                            "institution": names.get(n.institution_id, ""),
                            "institution_id": str(n.institution_id),
                            "cycle": n.cycle,
                            "days": str(n.days),
                            "due_utc": n.due_utc.isoformat(),
                        },
                        dedupe_key=n.dedupe_key,
                        scheduled_at=when if when > now else None,
                    )
                )
                queued += 1
            await uow.commit()
        return queued
