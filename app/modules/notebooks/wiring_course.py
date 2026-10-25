"""Students' notebooks of the LMS courses they are enrolled in (LMS-NB)."""

from dataclasses import dataclass

from app.modules.notebooks.application.provision_course_notebook import (
    BackfillCourseNotebooks,
    ProvisionCourseNotebook,
)
from app.modules.notebooks.application.readers.registry import SourceReaders
from app.modules.notebooks.application.sync_course_notebook import (
    SyncCourseNotebook,
    SyncCourseNotebooks,
)
from app.modules.notebooks.wiring_core import NotebooksCore
from app.shared.contracts.files import FilesApi
from app.shared.contracts.lms import LmsSourceReader


@dataclass(frozen=True, slots=True)
class CourseServices:
    """Use cases and jobs of the students' course notebooks (attribute = file name)."""

    provision_course_notebook: ProvisionCourseNotebook
    sync_course_notebook: SyncCourseNotebook
    sync_course_notebooks: SyncCourseNotebooks
    backfill_course_notebooks: BackfillCourseNotebooks


def build_course(
    core: NotebooksCore,
    *,
    readers: SourceReaders,
    lms: LmsSourceReader | None,
    files: FilesApi,
) -> CourseServices:
    """Build the course notebook use cases (without `lms` they do nothing)."""
    deps = core.deps
    sync = SyncCourseNotebook(
        uow_factory=core.uow_factory,
        clock=deps.clock,
        readers=readers,
        lms=lms,
        files=files,
        kicker=deps.kicker,
    )
    provision = ProvisionCourseNotebook(
        uow_factory=core.uow_factory, clock=deps.clock, lms=lms, sync=sync
    )
    return CourseServices(
        provision_course_notebook=provision,
        sync_course_notebook=sync,
        sync_course_notebooks=SyncCourseNotebooks(
            uow_factory=core.uow_factory, kicker=deps.kicker
        ),
        backfill_course_notebooks=BackfillCourseNotebooks(
            lms=lms,
            provision=provision,
            kicker=deps.kicker,
            uow_factory=core.uow_factory,
        ),
    )
