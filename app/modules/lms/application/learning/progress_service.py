"""Course progress: completed steps of the live version (LMS-14, LMS-19)."""

from datetime import datetime
from uuid import UUID

from app.modules.lms.domain.learning.entities import (
    Enrollment,
    LearningCourse,
    LiveVersion,
)
from app.modules.lms.domain.learning.progress import percent
from app.modules.lms.ports.learning.unit_of_work import LearningUnitOfWork


async def refresh_progress(
    uow: LearningUnitOfWork,
    enrollment: Enrollment,
    version: LiveVersion,
    now: datetime,
) -> None:
    """Recompute progress against a version and store it.

    ``completed_at`` is set when progress first reaches 100 % and is kept if a
    later version adds steps (the percentage may go down, the history stays).
    """
    step_ids = version.manifest.step_ids()
    done = await uow.states.completed_step_ids(enrollment.user_id, step_ids)
    enrollment.progress_pct = percent(len(done), len(step_ids))
    enrollment.progress_version_id = version.id
    if enrollment.progress_pct == 100 and enrollment.completed_at is None:
        enrollment.completed_at = now
    await uow.enrollments.save(enrollment)


async def ensure_progress(
    uow: LearningUnitOfWork,
    enrollment: Enrollment,
    version: LiveVersion,
    now: datetime,
) -> None:
    """Recompute progress lazily, only when it was computed for another version."""
    if enrollment.progress_version_id != version.id:
        await refresh_progress(uow, enrollment, version, now)


async def refresh_user_progress(
    uow: LearningUnitOfWork, user_id: UUID, course: LearningCourse, now: datetime
) -> None:
    """Recompute the progress of a user in a course after a step changed state."""
    if course.live_version_id is None:
        return
    enrollment = await uow.enrollments.get(course.id, user_id)
    version = await uow.versions.get(course.live_version_id)
    if enrollment is not None and version is not None:
        await refresh_progress(uow, enrollment, version, now)
