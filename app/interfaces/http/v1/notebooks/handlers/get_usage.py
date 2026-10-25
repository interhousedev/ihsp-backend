"""GET /v1/notebooks/usage."""

from app.interfaces.http.v1.notebooks.deps import Notebooks, OwnerActor
from app.interfaces.http.v1.notebooks.schemas_common import NotebookUsageResponse


async def get_usage(notebooks: Notebooks, actor: OwnerActor) -> NotebookUsageResponse:
    """Return the student's budget, daily quotas and running outputs."""
    view = await notebooks.get_usage.execute(actor.user_id)
    return NotebookUsageResponse.from_view(view)
