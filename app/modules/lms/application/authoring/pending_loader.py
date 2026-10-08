"""Loading everything needed to compare a draft with the live version."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.lms.domain.authoring.entities import Course, CourseStep, CourseVersion
from app.modules.lms.domain.authoring.manifest import (
    ManifestStep,
    manifest_steps,
    parse_manifest,
)
from app.modules.lms.domain.authoring.outline import step_ids_in
from app.modules.lms.domain.authoring.pending import (
    Pending,
    StepSnapshot,
    compute_pending,
)
from app.modules.lms.ports.authoring.unit_of_work import AuthoringUnitOfWork


@dataclass(slots=True)
class PendingContext:
    """Pending changes with the rows they were computed from."""

    pending: Pending
    steps: dict[UUID, CourseStep]
    live_version: CourseVersion | None
    manifest: list[ManifestStep]


async def load_live_manifest(
    uow: AuthoringUnitOfWork, course: Course
) -> tuple[CourseVersion | None, list[ManifestStep]]:
    """Return the live version of a course and its steps (empty if unpublished)."""
    if course.live_version_id is None:
        return None, []
    version = await uow.versions.get(course.live_version_id)
    if version is None:
        return None, []
    return version, manifest_steps(parse_manifest(version.outline))


async def load_pending(uow: AuthoringUnitOfWork, course: Course) -> PendingContext:
    """Compute the pending changes of a course from hashes."""
    steps = await uow.steps.get_many(step_ids_in(course.draft_outline))
    live_version, manifest = await load_live_manifest(uow, course)
    snapshots = {
        step_id: StepSnapshot(
            step_id=step_id,
            title=step.title,
            draft_hash=step.draft_hash,
            live_hash=step.live_hash,
            live_revision_id=step.live_revision_id,
            via=step.draft_updated_via,
        )
        for step_id, step in steps.items()
    }
    pending = compute_pending(
        draft_seq=course.draft_seq,
        outline_hash=course.outline_hash,
        live_outline_hash=course.live_outline_hash,
        outline=course.draft_outline,
        snapshots=snapshots,
        live=manifest,
    )
    return PendingContext(pending, steps, live_version, manifest)
