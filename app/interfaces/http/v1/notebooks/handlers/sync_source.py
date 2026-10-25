"""POST /v1/notebooks/{id}/sources/{sid}/sync."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, Notebooks
from app.interfaces.http.v1.notebooks.schemas_common import SourceItemResponse


async def sync_source(
    notebook_id: UUID, source_id: UUID, notebooks: Notebooks, actor: MemberActor
) -> SourceItemResponse:
    """Read the source again (a changed file, a chat with new messages)."""
    source = await notebooks.sync_source.execute(actor, notebook_id, source_id)
    return SourceItemResponse.from_entity(source)
