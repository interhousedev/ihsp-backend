"""POST /v1/notebooks/{id}/labels/auto."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, Notebooks
from app.interfaces.http.v1.notebooks.schemas_labels import StartLabelsResponse


async def start_labeling(
    notebook_id: UUID, notebooks: Notebooks, actor: MemberActor
) -> StartLabelsResponse:
    """Label the selected, ready sources by topic in the background."""
    run = await notebooks.start_labeling.execute(actor, notebook_id)
    return StartLabelsResponse(status=run.status)
