"""Task admission.deadline_reminders: queue due deadline reminders."""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="admission.deadline_reminders")
async def deadline_reminders() -> int:
    """Hourly; returns the number of reminders queued in the notify outbox.

    Milestone reminders, then calendar reminders (list rounds, checklist, exams,
    opportunities); each has its own dedupe keys.
    """
    admission = get_container().admission
    queued = int(await admission.deadlines.run_reminders())
    return queued + int(await admission.calendar.run_reminders())
