"""Task notebooks.provision_course_notebook: a student's notebook of a course."""

from uuid import UUID

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(
    task_name="notebooks.provision_course_notebook",
    retry_on_error=True,
    max_retries=3,
)
async def provision_course_notebook(user_id: UUID, course_id: UUID) -> bool:
    """Create (and fill) the notebook after an enrollment; True when it exists."""
    provision = get_container().notebooks.provision_course_notebook
    return await provision.execute(user_id, course_id) is not None
