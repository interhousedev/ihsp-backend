"""Use case: start the automatic labeling of the selected sources (G12/G13)."""

from functools import partial
from uuid import UUID

from app.modules.notebooks.application.access import load_notebook
from app.modules.notebooks.domain.label_errors import (
    LabelsNothingToLabelError,
    LabelsRunningError,
)
from app.modules.notebooks.domain.labels import (
    SOURCE_LABELS_RUN_TASK,
    LabelRun,
    LabelRunStatus,
)
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.tasks import TaskKicker


class StartLabeling:
    """Marks the notebook `running` and queues `notebooks.label_sources`."""

    def __init__(
        self, *, uow_factory: UowFactory, clock: Clock, kicker: TaskKicker
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.kicker = kicker

    async def execute(self, actor: Actor, notebook_id: UUID) -> LabelRun:
        """Start a run for the selected, ready sources; the job starts after commit.

        A run that has been `running` for more than 10 minutes counts as dead, so a
        lost job never blocks the notebook.

        Raises:
            NotebookNotFoundError: The notebook is not the caller's.
            WorkspaceReadOnlyError: A course member who may only read.
            LabelsRunningError: A run is going.
            LabelsNothingToLabelError: No source is selected and ready.
        """
        now = self.clock.now()
        async with self.uow_factory() as uow:
            await load_notebook(uow, actor.user_id, notebook_id, for_update=True)
            previous = await uow.labels.get_run(notebook_id) or LabelRun(notebook_id)
            if previous.is_running(now):
                raise LabelsRunningError()
            sources = await uow.sources.list_for_notebook(notebook_id)
            if not any(source.selected and source.usable for source in sources):
                raise LabelsNothingToLabelError()
            run = LabelRun(
                notebook_id=notebook_id,
                status=LabelRunStatus.RUNNING,
                started_at=now,
                finished_at=previous.finished_at,
                started_by=actor.user_id,
            )
            await uow.labels.save_run(run)
            uow.after_commit(
                partial(
                    self.kicker.kick,
                    SOURCE_LABELS_RUN_TASK,
                    notebook_id=str(notebook_id),
                )
            )
            await uow.commit()
        return run
