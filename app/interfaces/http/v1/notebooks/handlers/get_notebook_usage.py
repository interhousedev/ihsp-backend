"""GET /v1/notebooks/{id}/usage."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, Notebooks
from app.interfaces.http.v1.notebooks.schemas_common import NotebookUsageResponse


async def get_notebook_usage(
    notebook_id: UUID, notebooks: Notebooks, actor: MemberActor
) -> NotebookUsageResponse:
    """Return the caller's budget and quotas of the pool this notebook uses."""
    view = await notebooks.get_notebook_usage.execute(actor, notebook_id)
    return NotebookUsageResponse.from_view(view)
