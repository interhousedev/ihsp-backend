"""Use case: the budget and quotas that apply to one notebook (course pool or not)."""

from uuid import UUID

from app.modules.notebooks.application.access import load_notebook
from app.modules.notebooks.application.get_usage import GetUsage
from app.modules.notebooks.application.views import NotebookUsageView
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor


class GetNotebookUsage:
    """Reads `GET /v1/notebooks/{id}/usage`: the caller's usage of the right pool.

    A course workspace is paid from the course staff pool (shared with the author
    assistant), any other notebook from the student pool; the counters are always
    the caller's own.
    """

    def __init__(self, *, uow_factory: UowFactory, usage: GetUsage) -> None:
        """Store the unit of work factory and the usage reader."""
        self.uow_factory = uow_factory
        self.usage = usage

    async def execute(self, actor: Actor, notebook_id: UUID) -> NotebookUsageView:
        """Return the caller's budget, quotas and running outputs for the notebook.

        Raises:
            NotebookNotFoundError: Not a notebook the caller may read.
        """
        async with self.uow_factory() as uow:
            notebook = await load_notebook(uow, actor.user_id, notebook_id, write=False)
        return await self.usage.execute(
            actor.user_id, course=notebook.is_course_workspace
        )
