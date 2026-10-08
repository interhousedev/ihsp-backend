"""Copying a published version into the draft (restore, discard)."""

from datetime import datetime
from uuid import UUID

from app.modules.lms.application.authoring.draft_writer import (
    PreparedContent,
    StepDraftWriter,
)
from app.modules.lms.application.authoring.outline_editor import record_draft_change
from app.modules.lms.domain.authoring.entities import Course, CourseVersion
from app.modules.lms.domain.authoring.enums import StepVia
from app.modules.lms.domain.authoring.errors import (
    RevisionNotFoundError,
    StepNotFoundError,
)
from app.modules.lms.domain.authoring.manifest import (
    manifest_steps,
    outline_from_manifest,
    parse_manifest,
)
from app.modules.lms.ports.authoring.unit_of_work import AuthoringUnitOfWork


async def copy_version_into_draft(
    uow: AuthoringUnitOfWork,
    course: Course,
    version: CourseVersion,
    *,
    actor_id: UUID,
    now: datetime,
) -> None:
    """Make the draft equal to a version: meta, outline and each step's content.

    The caller holds the course row lock. Steps that are not in the version leave
    the outline but keep their rows and revisions. Only steps whose content
    differs get a new lock version.
    """
    sections = parse_manifest(version.outline)
    entries = manifest_steps(sections)
    steps = await uow.steps.get_many([e.step_id for e in entries])
    revisions = await uow.revisions.get_many([e.revision_id for e in entries])
    for entry in entries:
        step = steps.get(entry.step_id)
        revision = revisions.get(entry.revision_id)
        if step is None:
            raise StepNotFoundError(params={"step_id": str(entry.step_id)})
        if revision is None:
            raise RevisionNotFoundError(params={"revision_id": str(entry.revision_id)})
        if step.draft_hash == revision.content_hash:
            continue
        StepDraftWriter.apply(
            step,
            PreparedContent.from_revision(revision),
            by=actor_id,
            via=StepVia.UI,
            now=now,
        )
        await uow.steps.save_draft(step)
    course.draft_meta = dict(version.meta)
    record_draft_change(
        course, outline=outline_from_manifest(sections), actor_id=actor_id, now=now
    )
    await uow.courses.save(course)
