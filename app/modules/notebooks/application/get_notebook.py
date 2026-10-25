"""Use case: open a notebook (NB-2)."""

from functools import partial
from uuid import UUID

from app.modules.notebooks.application.access import load_notebook
from app.modules.notebooks.domain.auto_notebook import sync_is_stale
from app.modules.notebooks.domain.entities import Notebook
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.tasks import TaskKicker


class GetNotebook:
    """Returns the student's notebook and notes that it was opened."""

    def __init__(
        self, *, uow_factory: UowFactory, clock: Clock, kicker: TaskKicker
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.kicker = kicker

    async def execute(self, actor: Actor, notebook_id: UUID) -> Notebook:
        """Set `last_opened_at` and return the notebook.

        Opening is not an edit: `updated_at` stays as it was. A subject or lesson
        notebook that was not synced for a while is synced in the background.
        """
        async with self.uow_factory() as uow:
            notebook = await load_notebook(
                uow, actor.user_id, notebook_id, for_update=True, write=False
            )
            now = self.clock.now()
            notebook.last_opened_at = now
            await uow.notebooks.save(notebook)
            if notebook.is_auto and sync_is_stale(notebook.auto_synced_at, now):
                uow.after_commit(
                    partial(
                        self.kicker.kick,
                        "notebooks.sync_auto_notebook",
                        notebook_id=str(notebook.id),
                    )
                )
            await uow.commit()
        return notebook
