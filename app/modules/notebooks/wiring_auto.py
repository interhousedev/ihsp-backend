"""Subject and lesson notebooks the system keeps in step with the lessons (NB-AUTO)."""

from dataclasses import dataclass

from app.modules.notebooks.application.auto_targets import AutoTargets
from app.modules.notebooks.application.open_auto_notebook import OpenAutoNotebook
from app.modules.notebooks.application.readers.registry import SourceReaders
from app.modules.notebooks.application.sweep_auto_notebooks import SweepAutoNotebooks
from app.modules.notebooks.application.sync_auto_notebook import SyncAutoNotebook
from app.modules.notebooks.application.sync_lesson_notebooks import SyncLessonNotebooks
from app.modules.notebooks.application.update_auto_settings import UpdateAutoSettings
from app.modules.notebooks.ports.term_calendar import TermCalendar
from app.modules.notebooks.wiring_core import NotebooksCore
from app.shared.contracts.academic import ClassworkQueries, ScheduleQueries
from app.shared.contracts.links import LinksApi


@dataclass(frozen=True, slots=True)
class AutoServices:
    """Use cases and jobs of auto notebooks (attribute = file name)."""

    open_auto_notebook: OpenAutoNotebook
    update_auto_settings: UpdateAutoSettings
    sync_auto_notebook: SyncAutoNotebook
    sync_lesson_notebooks: SyncLessonNotebooks
    sweep_auto_notebooks: SweepAutoNotebooks


def build_auto(
    core: NotebooksCore,
    *,
    readers: SourceReaders,
    links: LinksApi,
    schedule: ScheduleQueries,
    classwork: ClassworkQueries | None,
    terms: TermCalendar | None,
) -> AutoServices:
    """Build the auto notebook use cases.

    Without `classwork` and `terms` they answer "feature disabled" (the lessons of a
    subject in this term are unknown).
    """
    deps = core.deps
    targets = AutoTargets(
        schedule=schedule, classwork=classwork, terms=terms, clock=deps.clock
    )
    sync = SyncAutoNotebook(
        uow_factory=core.uow_factory,
        clock=deps.clock,
        settings=deps.settings,
        readers=readers,
        links=links,
        targets=targets,
        kicker=deps.kicker,
    )
    return AutoServices(
        open_auto_notebook=OpenAutoNotebook(
            uow_factory=core.uow_factory,
            clock=deps.clock,
            targets=targets,
            sync=sync,
            kicker=deps.kicker,
        ),
        update_auto_settings=UpdateAutoSettings(
            uow_factory=core.uow_factory, clock=deps.clock, sync=sync
        ),
        sync_auto_notebook=sync,
        sync_lesson_notebooks=SyncLessonNotebooks(
            uow_factory=core.uow_factory, schedule=schedule, kicker=deps.kicker
        ),
        sweep_auto_notebooks=SweepAutoNotebooks(
            uow_factory=core.uow_factory, clock=deps.clock, kicker=deps.kicker
        ),
    )
