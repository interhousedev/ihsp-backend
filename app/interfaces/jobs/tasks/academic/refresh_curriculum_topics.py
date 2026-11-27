"""Task ``academic.refresh_curriculum_topics``: grow the topic directory.

The question bank's catalogue is `academic.curriculum_topics`; EMIS gives only the
topic of each held class, so the directory is derived from them nightly.
"""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="academic.refresh_curriculum_topics")
async def refresh_curriculum_topics() -> int:
    """Add the new lesson topics to the directory; return how many were added."""
    container = get_container()
    added: int = await container.academic.curriculum_topics.execute()
    return added
