"""POST /v1/notebooks/{id}/sources/select."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, Notebooks
from app.interfaces.http.v1.notebooks.schemas_common import SourceItemResponse
from app.interfaces.http.v1.notebooks.schemas_sources import SelectSourcesBody


async def select_sources(
    notebook_id: UUID,
    body: SelectSourcesBody,
    notebooks: Notebooks,
    actor: MemberActor,
) -> list[SourceItemResponse]:
    """Tick or untick some sources, or all of them when `ids` is absent."""
    sources = await notebooks.select_sources.execute(
        actor, notebook_id, body.selected, body.ids
    )
    return [SourceItemResponse.from_entity(s) for s in sources]
