"""Task ``lms.certificate_sweep``: issue the course certificates learners earned.

Desired schedule: every 5 minutes. Learners who never open the certificate card
still get their certificate; issuing is idempotent and never downgrades a tier.
"""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container

import structlog

log = structlog.get_logger(__name__)


@broker.task(task_name="lms.certificate_sweep")
async def certificate_sweep() -> dict[str, int]:
    """Issue or upgrade certificates in every course with certificates on."""
    container = get_container()
    held = await container.course_certificates.sweep()
    log.info("lms_certificates_swept", held=held)
    return {"held": held}
