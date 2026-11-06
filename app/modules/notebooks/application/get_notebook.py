"""Use case: open a notebook (NB-2)."""

from dataclasses import replace
from functools import partial
from uuid import UUID

from app.modules.notebooks.application.access import load_notebook
from app.modules.notebooks.domain.auto_notebook import sync_is_stale
from app.modules.notebooks.domain.entities import ChatConfig, Notebook, Source
from app.modules.notebooks.domain.sharing import viewable
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.tasks import TaskKicker


def _viewer_notebook(notebook: Notebook, sources: list[Source]) -> Notebook:
    """What a person the notebook is shared with sees; the owner's row is untouched.

    The owner's chat settings are private and are not applied to them. The summary is
    left out when it may quote a source they cannot see.
    """
    shown = viewable(sources)
    return replace(
        notebook,
        pinned=False,
        last_opened_at=None,
        chat_config=ChatConfig(),
        summary=notebook.summary if len(shown) == len(sources) else None,
        source_count=len(shown),
        ready_source_count=sum(s.usable for s in shown),
        selected_source_count=sum(s.usable for s in shown),
    )


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
                uow, actor.user_id, notebook_id, write=False, shared=True
            )
            if notebook.shared_view:
                sources = await uow.sources.list_for_notebook(notebook_id)
                return _viewer_notebook(notebook, sources)
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
