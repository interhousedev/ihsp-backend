"""Loading a presentation plan the caller owns (PLAN)."""

from uuid import UUID

from app.modules.notebooks.application.access import load_notebook
from app.modules.notebooks.domain.errors import NotebookNotFoundError
from app.modules.notebooks.domain.presentation_plan import PresentationPlan
from app.modules.notebooks.ports.unit_of_work import NotebooksUnitOfWork


async def load_own_plan(
    uow: NotebooksUnitOfWork,
    user_id: UUID,
    notebook_id: UUID,
    plan_id: UUID,
    *,
    for_update: bool = False,
) -> PresentationPlan:
    """Return the caller's plan of this notebook, else `NotebookNotFoundError`."""
    await load_notebook(uow, user_id, notebook_id, write=for_update)
    plans = uow.plans
    plan = await (plans.get_for_update(plan_id) if for_update else plans.get(plan_id))
    if plan is None or plan.notebook_id != notebook_id or plan.owner_id != user_id:
        raise NotebookNotFoundError()
    return plan
