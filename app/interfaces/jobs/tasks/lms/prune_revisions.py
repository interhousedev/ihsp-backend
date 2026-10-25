"""Task `lms.prune_revisions`: delete old checkpoints and previews (LMS-12).

Desired schedule (declared by I1 in `app/interfaces/jobs/schedule.py`): daily at
03:30, `Asia/Tashkent`.
"""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container

import structlog

log = structlog.get_logger(__name__)


@broker.task(task_name="lms.prune_revisions")
async def prune_revisions() -> dict[str, int]:
    """Keep the newest 20 checkpoints per step and 30 days of previews."""
    container = get_container()
    result = await container.lms.authoring.prune_revisions.execute()
    log.info(
        "lms_revisions_pruned",
        checkpoints=result.checkpoints,
        previews=result.previews,
    )
    return {"checkpoints": result.checkpoints, "previews": result.previews}
