"""Task ``academic.generate_assessments``: suggest controls from EMIS exam lessons.

Desired schedule: 02:30 and 20:30 (after the lesson generation and the last EMIS sync).
"""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="academic.generate_assessments")
async def generate_assessments() -> dict[str, int]:
    """Create the controls EMIS lessons suggest and confirm those inside a week."""
    container = get_container()
    result: dict[str, int] = (
        await container.academic.assessments.generate_suggestions.execute()
    )
    return result
