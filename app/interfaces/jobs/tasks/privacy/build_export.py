"""Task ``privacy.build_export``: pack a user's data into a ZIP archive."""

from uuid import UUID

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="privacy.build_export")
async def build_export(export_id: UUID) -> bool:
    """Return False when the export was gone, taken or failed."""
    return bool(await get_container().privacy.build_export.execute(export_id))
