"""Use case: the labels of a notebook and the state of the auto labeling (G12)."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.notebooks.application.access import load_notebook
from app.modules.notebooks.domain.labels import LabelRun, SourceLabel
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock


@dataclass(frozen=True, slots=True)
class LabelListing:
    """The labels by position and what the automatic labeling is doing."""

    items: list[SourceLabel]
    auto: LabelRun


class ListLabels:
    """Reads the labels of a notebook; any reader of the notebook may."""

    def __init__(self, *, uow_factory: UowFactory, clock: Clock) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def execute(self, actor: Actor, notebook_id: UUID) -> LabelListing:
        """Return the labels with their source counts and the auto run state.

        A run that has been `running` for too long is shown as `failed`.

        Raises:
            NotebookNotFoundError: The notebook is not the caller's.
        """
        async with self.uow_factory() as uow:
            await load_notebook(uow, actor.user_id, notebook_id, write=False)
            items = await uow.labels.list_for_notebook(notebook_id)
            run = await uow.labels.get_run(notebook_id) or LabelRun(notebook_id)
        return LabelListing(items=items, auto=run.shown(self.clock.now()))
