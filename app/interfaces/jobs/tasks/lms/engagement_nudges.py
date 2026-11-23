"""Task ``lms.engagement_nudges``: review due, streak at risk and deadline soon.

Desired schedule: weekdays at 17:00 (Tashkent time). Learners get only the types
they turned on; nothing goes out on weekends or from 21:00 to 08:00.
"""

from dataclasses import asdict
from typing import Any

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="lms.engagement_nudges")
async def engagement_nudges() -> dict[str, Any]:
    """Queue today's LMS nudges for the learners who opted in."""
    container = get_container()
    report = await container.notify.lms_nudges.execute(container.lms.engagement)
    return asdict(report)
