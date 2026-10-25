"""Task notebooks.provision_student_notebooks: create a student's subject notebooks."""

from uuid import UUID

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(
    task_name="notebooks.provision_student_notebooks",
    retry_on_error=True,
    max_retries=3,
)
async def provision_student_notebooks(user_id: UUID) -> int:
    """Create (and fill) the missing subject notebooks of this term; return how many."""
    provision = get_container().notebooks.provision_student_notebooks
    return int(await provision.execute(user_id))
