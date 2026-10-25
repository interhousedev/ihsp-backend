"""Task ``academic.temporary_mark_reminders``: temporary marks to move to EMIS (TMP-3).

Desired schedule: every 15 minutes from 12:00 to 20:45, Monday to Friday; the
use case waits until the day's lessons ended and sends once per teacher and day.
"""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="academic.temporary_mark_reminders")
async def temporary_mark_reminders() -> dict[str, int]:
    """Queue the day's temporary-marks reminder per teacher, once lessons end."""
    container = get_container()
    result: dict[str, int] = (
        await container.academic.classwork.send_temporary_mark_reminders.execute()
    )
    return result
