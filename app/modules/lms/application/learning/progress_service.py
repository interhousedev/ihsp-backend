"""Course progress: completed steps of the live version (LMS-14, LMS-19)."""

from datetime import datetime
from uuid import UUID

from app.modules.lms.application.badges import award_badges
from app.modules.lms.application.learning.audience import AudienceGate
from app.modules.lms.domain.learning.entities import (
    Enrollment,
    LearningCourse,
    LiveVersion,
)
from app.modules.lms.domain.learning.progress import percent
from app.modules.lms.ports.learning.unit_of_work import LearningUnitOfWork


async def current_progress_pct(
    uow: LearningUnitOfWork,
    gate: AudienceGate,
    enrollment: Enrollment,
    version: LiveVersion,
) -> int:
    """Return the progress against a version without storing anything.

    The stored value when it was computed for this version, else the same
    computation ``refresh_progress`` does, minus the writes and badges.
    """
    if enrollment.progress_version_id == version.id:
        return enrollment.progress_pct
    actor = await gate.actor_for(enrollment.user_id)
    access = await gate.course(uow, actor, enrollment.course_id)
    step_ids = access.readable(version.manifest.step_ids())
    done = await uow.states.completed_step_ids(enrollment.user_id, step_ids)
    return percent(len(done), len(step_ids))


async def refresh_progress(
    uow: LearningUnitOfWork,
    gate: AudienceGate,
    enrollment: Enrollment,
    version: LiveVersion,
    now: datetime,
) -> None:
    """Recompute progress against a version and store it.

    Only the steps the learner may open count: a hidden or locked step neither
    blocks 100 % nor reveals itself through the percentage. ``completed_at`` is
    set when progress first reaches 100 % and is kept if a later version adds
    steps (the percentage may go down, the history stays).
    """
    actor = await gate.actor_for(enrollment.user_id)
    access = await gate.course(uow, actor, enrollment.course_id)
    step_ids = access.readable(version.manifest.step_ids())
    done = await uow.states.completed_step_ids(enrollment.user_id, step_ids)
    enrollment.progress_pct = percent(len(done), len(step_ids))
    enrollment.progress_version_id = version.id
    if enrollment.progress_pct == 100 and enrollment.completed_at is None:
        enrollment.completed_at = now
    await uow.enrollments.save(enrollment)
    await award_badges(uow, enrollment, version.manifest, now)


async def ensure_progress(
    uow: LearningUnitOfWork,
    gate: AudienceGate,
    enrollment: Enrollment,
    version: LiveVersion,
    now: datetime,
) -> None:
    """Recompute progress lazily, only when it was computed for another version."""
    if enrollment.progress_version_id != version.id:
        await refresh_progress(uow, gate, enrollment, version, now)


async def refresh_user_progress(
    uow: LearningUnitOfWork,
    gate: AudienceGate,
    user_id: UUID,
    course: LearningCourse,
    now: datetime,
) -> None:
    """Recompute the progress of a user in a course after a step changed state."""
    if course.live_version_id is None:
        return
    enrollment = await uow.enrollments.get(course.id, user_id)
    version = await uow.versions.get(course.live_version_id)
    if enrollment is not None and version is not None:
        await refresh_progress(uow, gate, enrollment, version, now)
