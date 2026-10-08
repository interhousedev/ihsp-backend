"""Use case: publish the pending changes as a new version (LMS-9, UF-LMS-10)."""

from datetime import datetime
from uuid import UUID

from app.modules.lms.application.authoring.access import (
    access_to,
    load_course_locked,
)
from app.modules.lms.application.authoring.pending_loader import (
    PendingContext,
    load_pending,
)
from app.modules.lms.application.authoring.presenter import Presenter, version_item
from app.modules.lms.application.authoring.uow_factory import UowFactory
from app.modules.lms.application.authoring.views import VersionItemView
from app.modules.lms.domain.authoring.entities import Course, CourseVersion
from app.modules.lms.domain.authoring.enums import RevisionKind, StepChange
from app.modules.lms.domain.authoring.errors import (
    DraftChangedError,
    NothingToPublishError,
)
from app.modules.lms.domain.authoring.manifest import build_manifest
from app.modules.lms.domain.authoring.outline import step_ids_in
from app.modules.lms.domain.authoring.permissions import PUBLISH
from app.modules.lms.ports.authoring.unit_of_work import AuthoringUnitOfWork
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.ids import new_id


class PublishCourse:
    """Freeze changed steps, write a version manifest and point the course at it."""

    def __init__(
        self, uow_factory: UowFactory, clock: Clock, presenter: Presenter
    ) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.presenter = presenter

    async def execute(
        self, actor: Actor, course_id: UUID, *, draft_seq: int, note: str | None
    ) -> VersionItemView:
        """Publish in one transaction; refuse if the draft moved since review.

        Raises:
            DraftChangedError: `draft_seq` is not the one the publisher reviewed.
            NothingToPublishError: The draft equals the live version.
        """
        now = self.clock.now()
        async with self.uow_factory() as uow:
            course = await load_course_locked(uow, course_id)
            access = await access_to(uow, actor, course_id)
            access.require(PUBLISH)
            if course.draft_seq != draft_seq:
                raise DraftChangedError(params={"draft_seq": course.draft_seq})
            context = await load_pending(uow, course)
            if context.pending.is_empty:
                raise NothingToPublishError()
            version = await self._publish(uow, course, context, actor, note, now)
            await uow.commit()
        author = (await self.presenter.people([actor.user_id]))[actor.user_id]
        return version_item(version, author)

    async def _publish(
        self,
        uow: AuthoringUnitOfWork,
        course: Course,
        context: PendingContext,
        actor: Actor,
        note: str | None,
        now: datetime,
    ) -> CourseVersion:
        pinned: dict[UUID, UUID] = {}
        fresh: list[UUID] = []
        for step_id in step_ids_in(course.draft_outline):
            step = context.steps[step_id]
            if step.live_revision_id is None or step.draft_hash != step.live_hash:
                revision = await uow.revisions.ensure(
                    step_id=step.id,
                    content=step.draft,
                    content_hash=step.draft_hash,
                    kind=RevisionKind.PUBLISH,
                    label=None,
                    file_ids=step.file_ids,
                    created_by=actor.user_id,
                    now=now,
                )
                fresh.append(revision.id)
                step.live_revision_id = revision.id
                step.live_hash = step.draft_hash
                await uow.steps.set_live(
                    step.id, revision_id=revision.id, live_hash=step.draft_hash
                )
            pinned[step_id] = step.live_revision_id
        await uow.revisions.mark_published(fresh, now)
        removed = [p.step_id for p in context.pending.of(StepChange.REMOVED)]
        await uow.steps.clear_live(removed)
        version = CourseVersion(
            id=new_id(),
            course_id=course.id,
            number=await uow.versions.next_number(course.id),
            meta=dict(course.draft_meta),
            outline=build_manifest(
                course.draft_outline,
                pinned,
                {sid: context.steps[sid].title for sid in pinned},
            ),
            changes=_changes(context),
            note=(note or "").strip() or None,
            published_by=actor.user_id,
            created_at=now,
        )
        await uow.versions.add(version)
        course.live_version_id = version.id
        course.title = course.draft_meta["title"]
        course.description = course.draft_meta["description"]
        course.live_outline_hash = course.outline_hash
        await uow.courses.save(course)
        return version


def _changes(context: PendingContext) -> dict[str, object]:
    pending = context.pending
    return {
        "added": [str(s.step_id) for s in pending.of(StepChange.ADDED)],
        "changed": [str(s.step_id) for s in pending.of(StepChange.CHANGED)],
        "removed": [str(s.step_id) for s in pending.of(StepChange.REMOVED)],
        "outline_changed": pending.outline_changed,
    }
