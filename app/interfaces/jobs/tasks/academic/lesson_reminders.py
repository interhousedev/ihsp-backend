"""Task ``academic.lesson_reminders``: queue lesson reminders (UF-SYS-06).

Desired schedule for I1: every minute (``* * * * *``).
"""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="academic.lesson_reminders")
async def lesson_reminders() -> dict[str, int]:
    """Queue resource messages and end-of-lesson prompts that are due now."""
    container = get_container()
    result: dict[str, int] = (
        await container.academic.classwork.lesson_reminders.execute()
    )
    return result
