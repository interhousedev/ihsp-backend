"""GET /v1/notebooks/{id}/labels."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, Notebooks
from app.interfaces.http.v1.notebooks.schemas_labels import LabelListResponse


async def list_labels(
    notebook_id: UUID, notebooks: Notebooks, actor: MemberActor
) -> LabelListResponse:
    """List the topic labels with their source counts and the auto labeling state."""
    listing = await notebooks.list_labels.execute(actor, notebook_id)
    return LabelListResponse.from_listing(listing)
