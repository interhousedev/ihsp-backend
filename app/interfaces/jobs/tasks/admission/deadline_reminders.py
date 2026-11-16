"""Task admission.deadline_reminders: queue due deadline reminders."""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="admission.deadline_reminders")
async def deadline_reminders() -> int:
    """Hourly; returns the number of reminders queued in the notify outbox."""
    return int(await get_container().admission.deadlines.run_reminders())
