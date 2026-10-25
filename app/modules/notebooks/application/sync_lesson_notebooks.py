"""Job `notebooks.sync_lesson_notebooks`: a lesson's materials changed (NB-AUTO)."""

from uuid import UUID

from app.modules.notebooks.domain.limits import AUTO_FANOUT_LIMIT
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.contracts.academic import ScheduleQueries
from app.shared.tasks import TaskKicker

import structlog

log = structlog.get_logger(__name__)


class SyncLessonNotebooks:
    """Starts a sync of every auto notebook that feeds on the lesson.

    Links kicks this task whenever a material or a student's file is added, hidden or
    removed. The notebooks are the students' subject notebooks of the lesson's
    subject and their notebooks of this lesson; each is synced by its own job.
    """

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        schedule: ScheduleQueries,
        kicker: TaskKicker,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.schedule = schedule
        self.kicker = kicker

    async def execute(self, lesson_id: UUID) -> int:
        """Kick one sync per notebook; return how many."""
        lesson = await self.schedule.get_lesson(lesson_id)
        if lesson is None:
            return 0
        async with self.uow_factory() as uow:
            ids = await uow.notebooks.auto_ids_for_lesson(
                lesson.subject_id, lesson.id, AUTO_FANOUT_LIMIT
            )
        for notebook_id in ids:
            await self.kicker.kick(
                "notebooks.sync_auto_notebook", notebook_id=str(notebook_id)
            )
        if ids:
            log.info(
                "notebooks_lesson_fanout", lesson_id=str(lesson_id), notebooks=len(ids)
            )
        return len(ids)
