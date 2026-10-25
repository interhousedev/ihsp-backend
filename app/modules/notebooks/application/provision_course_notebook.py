"""Jobs `notebooks.provision_course_notebook` and the backfill (LMS-NB)."""

from dataclasses import dataclass
from typing import Final
from uuid import UUID

from app.modules.notebooks.application.open_course_workspace import workspace_title
from app.modules.notebooks.application.sync_course_notebook import SyncCourseNotebook
from app.modules.notebooks.domain.auto_notebook import sync_is_stale
from app.modules.notebooks.domain.entities import Notebook
from app.modules.notebooks.domain.enums import NotebookOrigin
from app.modules.notebooks.domain.errors import NotebookNotFoundError
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.clock import Clock
from app.shared.contracts.lms import LmsCourseMaterials, LmsSourceReader
from app.shared.ids import new_id
from app.shared.tasks import TaskKicker

import structlog

log = structlog.get_logger(__name__)

COURSE_NOTEBOOK_EMOJI: Final = "📚"


class ProvisionCourseNotebook:
    """Creates a student's notebook of an LMS course and fills it with the materials.

    Safe to run any number of times (enrollment, opening the page, the backfill):
    a student has one live notebook per course, and a second run only brings the
    sources up to date.
    """

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        clock: Clock,
        lms: LmsSourceReader | None,
        sync: SyncCourseNotebook,
    ) -> None:
        """Store the collaborators (`lms` missing: the feature is off)."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.lms = lms
        self.sync = sync

    async def execute(
        self, user_id: UUID, course_id: UUID, *, touch: bool = False
    ) -> Notebook | None:
        """Return the student's notebook of the course, created when missing.

        None when the student is not enrolled in a published course (or there is no
        LMS). `touch` counts as opening it and syncs it again when the last sync was
        a while ago; otherwise (the job) it is always synced.
        """
        if self.lms is None:
            return None
        materials = await self.lms.course_materials(user_id, course_id)
        if materials is None:
            return None
        notebook = await self._find(user_id, course_id)
        created = notebook is None
        if notebook is None:
            notebook = await self._create(user_id, materials)
        now = self.clock.now()
        if not touch or created or sync_is_stale(notebook.auto_synced_at, now):
            await self.sync.execute(notebook.id, materials)
        if touch:
            await self._touch(notebook.id)
        return await self._reload(notebook.id)

    async def _find(self, user_id: UUID, course_id: UUID) -> Notebook | None:
        async with self.uow_factory() as uow:
            return await uow.notebooks.find_course_student(user_id, course_id)

    async def _create(self, user_id: UUID, materials: LmsCourseMaterials) -> Notebook:
        """Store the empty notebook; on a lost race return the one that won."""
        now = self.clock.now()
        notebook = Notebook(
            id=new_id(),
            owner_id=user_id,
            title=workspace_title(materials.course_title),
            title_auto=False,
            emoji=COURSE_NOTEBOOK_EMOJI,
            emoji_auto=False,
            created_at=now,
            updated_at=now,
            last_opened_at=None,
            origin=NotebookOrigin.COURSE_STUDENT,
            course_id=materials.course_id,
        )
        async with self.uow_factory() as uow:
            if await uow.notebooks.add_course_student(notebook):
                await uow.commit()
                log.info(
                    "notebooks_course_notebook_created",
                    course_id=str(materials.course_id),
                )
                return notebook
            winner = await uow.notebooks.find_course_student(
                user_id, materials.course_id
            )
        if winner is None:
            raise NotebookNotFoundError(support_details="course notebook race lost")
        return winner

    async def _touch(self, notebook_id: UUID) -> None:
        async with self.uow_factory() as uow:
            notebook = await uow.notebooks.get(notebook_id)
            if notebook is None:
                return
            notebook.last_opened_at = self.clock.now()
            await uow.notebooks.save(notebook)
            await uow.commit()

    async def _reload(self, notebook_id: UUID) -> Notebook:
        """The notebook with fresh source counts."""
        async with self.uow_factory() as uow:
            notebook = await uow.notebooks.get(notebook_id)
        if notebook is None:
            raise NotebookNotFoundError()
        return notebook


@dataclass(frozen=True, slots=True)
class CourseBackfillResult:
    """What a backfill did: enrollments visited and notebooks created."""

    enrollments: int
    created: int


class BackfillCourseNotebooks:
    """Provisions the course notebooks of every enrollment that is already there.

    `python -m app backfill-course-notebooks` runs it in place; without `inline` it
    only queues one provisioning task per enrollment.
    """

    def __init__(
        self,
        *,
        lms: LmsSourceReader | None,
        provision: ProvisionCourseNotebook,
        kicker: TaskKicker,
        uow_factory: UowFactory,
    ) -> None:
        """Store the collaborators."""
        self.lms = lms
        self.provision = provision
        self.kicker = kicker
        self.uow_factory = uow_factory

    async def execute(self, *, inline: bool = False) -> CourseBackfillResult:
        """Visit every enrollment: do the work now (`inline`) or queue it."""
        if self.lms is None:
            return CourseBackfillResult(0, 0)
        pairs = await self.lms.enrollment_pairs()
        created = 0
        for course_id, user_id in pairs:
            if inline:
                had = await self._has(user_id, course_id)
                made = await self.provision.execute(user_id, course_id)
                created += int(made is not None and not had)
            else:
                await self.kicker.kick(
                    "notebooks.provision_course_notebook",
                    user_id=str(user_id),
                    course_id=str(course_id),
                )
        return CourseBackfillResult(len(pairs), created)

    async def _has(self, user_id: UUID, course_id: UUID) -> bool:
        async with self.uow_factory() as uow:
            found = await uow.notebooks.find_course_student(user_id, course_id)
        return found is not None
