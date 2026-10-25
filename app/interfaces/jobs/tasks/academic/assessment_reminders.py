"""Task ``academic.assessment_reminders``: remind students 7, 3 and 1 days ahead.

Desired schedule: daily at 07:30 (Tashkent time).
"""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="academic.assessment_reminders")
async def assessment_reminders() -> dict[str, int]:
    """Queue the `assessment_reminder` notifications that are due today."""
    container = get_container()
    result: dict[str, int] = (
        await container.academic.assessments.send_reminders.execute()
    )
    return result
