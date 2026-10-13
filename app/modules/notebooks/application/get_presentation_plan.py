"""Use case: read a presentation plan (PLAN)."""

from uuid import UUID

from app.modules.notebooks.application.presentation_plan_access import load_own_plan
from app.modules.notebooks.domain.presentation_plan import PresentationPlan
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor


class GetPresentationPlan:
    """Returns one of the caller's plans."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the unit of work factory."""
        self.uow_factory = uow_factory

    async def execute(
        self, actor: Actor, notebook_id: UUID, plan_id: UUID
    ) -> PresentationPlan:
        """Return the plan.

        Raises:
            NotebookNotFoundError: No such plan of the caller in this notebook.
        """
        async with self.uow_factory() as uow:
            return await load_own_plan(uow, actor.user_id, notebook_id, plan_id)
