"""Task notebooks.embed_passages: vectors for passages (after a source; backfill)."""

from uuid import UUID

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="notebooks.embed_passages", retry_on_error=True, max_retries=2)
async def embed_passages(document_id: UUID | None = None) -> dict[str, int]:
    """Embed the passages of one document, or the next ones that have no vector."""
    return dict(await get_container().notebooks.embed_passages.execute(document_id))
