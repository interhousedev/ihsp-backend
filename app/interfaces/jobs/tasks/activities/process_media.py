"""Task `activities.media.process`: build the derivatives of an uploaded club media."""

from uuid import UUID

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="activities.media.process", retry_on_error=True, max_retries=2)
async def process_media(media_id: UUID) -> None:
    """Sniff, strip, derive; the media becomes `ready` or `failed`. Idempotent."""
    await get_container().activities.media.process(media_id)
