"""Notebook CRUD and lifecycle jobs of the notebooks module (NB-1 to NB-3)."""

from dataclasses import dataclass

from app.modules.notebooks.application.copy_notebook import CopyNotebook
from app.modules.notebooks.application.create_notebook import CreateNotebook
from app.modules.notebooks.application.delete_notebook import DeleteNotebook
from app.modules.notebooks.application.delete_owner import DeleteOwner
from app.modules.notebooks.application.get_notebook import GetNotebook
from app.modules.notebooks.application.list_notebooks import ListNotebooks
from app.modules.notebooks.application.purge_deleted import PurgeDeleted
from app.modules.notebooks.application.purge_shared import PurgeShared
from app.modules.notebooks.application.sweep_stuck import SweepStuck
from app.modules.notebooks.application.update_notebook import UpdateNotebook
from app.modules.notebooks.wiring_core import NotebooksCore


@dataclass(frozen=True, slots=True)
class NotebooksLifecycleServices:
    """Use cases of notebooks and the lifecycle jobs (attribute = file name)."""

    create_notebook: CreateNotebook
    list_notebooks: ListNotebooks
    get_notebook: GetNotebook
    update_notebook: UpdateNotebook
    copy_notebook: CopyNotebook
    delete_notebook: DeleteNotebook
    purge_deleted: PurgeDeleted
    purge_shared: PurgeShared
    delete_owner: DeleteOwner
    sweep_stuck: SweepStuck


def build_notebooks(core: NotebooksCore) -> NotebooksLifecycleServices:
    """Build the notebook use cases and jobs over the shared services."""
    deps = core.deps
    return NotebooksLifecycleServices(
        create_notebook=CreateNotebook(
            uow_factory=core.uow_factory,
            clock=deps.clock,
            settings=deps.settings,
            i18n=deps.i18n,
            locale=core.locale,
        ),
        list_notebooks=ListNotebooks(uow_factory=core.uow_factory),
        get_notebook=GetNotebook(
            uow_factory=core.uow_factory, clock=deps.clock, kicker=deps.kicker
        ),
        update_notebook=UpdateNotebook(uow_factory=core.uow_factory, clock=deps.clock),
        copy_notebook=CopyNotebook(
            uow_factory=core.uow_factory,
            clock=deps.clock,
            settings=deps.settings,
            i18n=deps.i18n,
            locale=core.locale,
            kicker=deps.kicker,
        ),
        delete_notebook=DeleteNotebook(uow_factory=core.uow_factory, clock=deps.clock),
        purge_deleted=PurgeDeleted(uow_factory=core.uow_factory, clock=deps.clock),
        purge_shared=PurgeShared(uow_factory=core.uow_factory, clock=deps.clock),
        delete_owner=DeleteOwner(uow_factory=core.uow_factory, quota=core.quota),
        sweep_stuck=SweepStuck(
            uow_factory=core.uow_factory,
            clock=deps.clock,
            kicker=deps.kicker,
            quota=core.quota,
        ),
    )
