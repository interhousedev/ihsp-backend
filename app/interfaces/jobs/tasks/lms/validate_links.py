"""Task `lms.validate_links`: check the URLs in a course's step drafts."""

from uuid import UUID

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container

import structlog

log = structlog.get_logger(__name__)


@broker.task(task_name="lms.validate_links")
async def validate_links(course_id: str, job_id: str) -> int:
    """Run the check and store the report on the course."""
    container = get_container()
    checked: int = await container.lms.authoring.validate_links.execute(
        UUID(course_id), job_id
    )
    log.info("lms_links_checked", course_id=course_id, links=checked)
    return checked
