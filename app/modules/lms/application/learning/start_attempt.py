"""Use case: start (or resume) a test attempt (UF-LMS-04, UF-LMS-09)."""

from datetime import datetime, timedelta
from uuid import UUID

from app.modules.lms.application.learning.attempt_finisher import AttemptFinisher
from app.modules.lms.application.learning.attempt_presenter import attempt_view
from app.modules.lms.application.learning.revision_loading import (
    find_test_block,
    load_revision,
)
from app.modules.lms.application.learning.step_context import (
    load_live_step,
    staff_access,
)
from app.modules.lms.application.learning.types import UowFactory
from app.modules.lms.application.learning.views import LearningAttemptView
from app.modules.lms.domain.learning.access import VIEW_DRAFTS
from app.modules.lms.domain.learning.entities import Attempt, LearningStep, RevisionData
from app.modules.lms.domain.learning.errors import (
    AttemptCooldownError,
    AttemptNumberTakenError,
    AttemptStartConflictError,
    NoAttemptsLeftError,
    NotEnrolledError,
    StepNotFoundError,
)
from app.modules.lms.domain.learning.variant import build_variant, max_score_of
from app.modules.lms.domain.step_content import TestBlock
from app.modules.lms.ports.learning.unit_of_work import LearningUnitOfWork
from app.modules.lms.ports.preview_revisions import PreviewRevisions
from app.shared.actor import Actor
from app.shared.base_error import BaseError
from app.shared.clock import Clock
from app.shared.ids import new_id

START_TRIES = 2


class StartAttempt:
    """Create an attempt bound to a revision, with its variant, or resume one."""

    def __init__(
        self,
        uow_factory: UowFactory,
        clock: Clock,
        finisher: AttemptFinisher,
        previews: PreviewRevisions,
    ) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.finisher = finisher
        self.previews = previews

    async def execute(
        self, actor: Actor, step_id: UUID, block_id: str, *, preview: bool
    ) -> LearningAttemptView:
        """Return the open attempt or a new one.

        A double click can race two inserts on the unique attempt number; the
        loser retries once and then finds the winner's attempt.
        """
        revision_id = await self._preview_revision(actor, step_id) if preview else None
        for _ in range(START_TRIES):
            try:
                return await self._start(actor, step_id, block_id, revision_id)
            except AttemptNumberTakenError:
                continue
        raise AttemptStartConflictError(params={"step_id": str(step_id)})

    async def _preview_revision(self, actor: Actor, step_id: UUID) -> UUID:
        """Check `view_drafts` and freeze the draft as a preview revision."""
        async with self.uow_factory() as uow:
            step = await _load_step(uow, step_id)
            (await staff_access(uow, actor, step.course_id)).require(VIEW_DRAFTS)
        return await self.previews.ensure_preview_revision(step_id, actor)

    async def _start(
        self, actor: Actor, step_id: UUID, block_id: str, preview_revision: UUID | None
    ) -> LearningAttemptView:
        """One try: resume an open attempt, refuse by the rules, or create one."""
        now = self.clock.now()
        preview = preview_revision is not None
        problem: BaseError | None = None
        async with self.uow_factory() as uow:
            revision = await self._revision(uow, actor, step_id, preview_revision)
            test = find_test_block(revision.content, block_id)
            await self.finisher.finish_expired(
                uow, actor.user_id, step_id, preview=preview, now=now
            )
            attempt = await self._open_attempt(
                uow, actor, step_id, block_id, preview_revision, now
            )
            if attempt is None:
                problem = (
                    None
                    if preview
                    else await self._refusal(uow, actor, step_id, block_id, test, now)
                )
                if problem is None:
                    attempt = await self._create(
                        uow, actor, step_id, revision, test, now, preview=preview
                    )
            view = (
                None if attempt is None else await _view(uow, attempt, revision, test)
            )
            await uow.commit()
        if view is None:
            raise problem or AttemptStartConflictError()
        return view

    async def _revision(
        self,
        uow: LearningUnitOfWork,
        actor: Actor,
        step_id: UUID,
        preview_revision: UUID | None,
    ) -> RevisionData:
        """Return the revision to attempt: the live one, or the frozen draft."""
        if preview_revision is not None:
            revision = await load_revision(uow, preview_revision)
            if revision.step_id != step_id:
                raise StepNotFoundError(params={"step_id": str(step_id)})
            return revision
        context = await load_live_step(uow, step_id)
        if await uow.enrollments.get(context.course.id, actor.user_id) is None:
            raise NotEnrolledError(params={"course_id": str(context.course.id)})
        return await load_revision(uow, context.live_step.revision_id)

    async def _open_attempt(
        self,
        uow: LearningUnitOfWork,
        actor: Actor,
        step_id: UUID,
        block_id: str,
        preview_revision: UUID | None,
        now: datetime,
    ) -> Attempt | None:
        """Return the unsubmitted attempt to resume, if there is one."""
        open_attempts = await uow.attempts.list_open(
            actor.user_id, step_id, preview=preview_revision is not None
        )
        return next(
            (
                attempt
                for attempt in open_attempts
                if attempt.block_id == block_id
                and not attempt.is_expired(now)
                and preview_revision in (None, attempt.revision_id)
            ),
            None,
        )

    async def _refusal(
        self,
        uow: LearningUnitOfWork,
        actor: Actor,
        step_id: UUID,
        block_id: str,
        test: TestBlock,
        now: datetime,
    ) -> BaseError | None:
        """Return the reason a new attempt is not allowed: limit or pause."""
        limit = test.config.max_attempts
        used = await uow.attempts.count(actor.user_id, step_id, block_id)
        if limit is not None and used >= limit:
            return NoAttemptsLeftError(params={"max_attempts": limit})
        pause = test.config.cooldown_sec
        last = await uow.attempts.last_submitted_at(actor.user_id, step_id, block_id)
        if pause and last is not None and now < last + timedelta(seconds=pause):
            available = last + timedelta(seconds=pause)
            return AttemptCooldownError(params={"available_at": available.isoformat()})
        return None

    async def _create(
        self,
        uow: LearningUnitOfWork,
        actor: Actor,
        step_id: UUID,
        revision: RevisionData,
        test: TestBlock,
        now: datetime,
        *,
        preview: bool,
    ) -> Attempt:
        """Insert a new attempt with its variant and deadline."""
        attempt_id = new_id()
        variant = build_variant(test, attempt_id)
        limit = test.config.time_limit_sec
        attempt = Attempt(
            id=attempt_id,
            user_id=actor.user_id,
            step_id=step_id,
            revision_id=revision.id,
            block_id=test.id,
            attempt_no=await uow.attempts.max_attempt_no(
                actor.user_id, step_id, test.id, preview=preview
            )
            + 1,
            is_preview=preview,
            variant=variant,
            started_at=now,
            deadline_at=now + timedelta(seconds=limit) if limit else None,
            max_score=max_score_of(test, variant),
        )
        await uow.attempts.add(attempt)
        return attempt


async def _load_step(uow: LearningUnitOfWork, step_id: UUID) -> LearningStep:
    """Return the step or raise StepNotFoundError."""
    step = await uow.steps.get(step_id)
    if step is None:
        raise StepNotFoundError(params={"step_id": str(step_id)})
    return step


async def _view(
    uow: LearningUnitOfWork, attempt: Attempt, revision: RevisionData, test: TestBlock
) -> LearningAttemptView:
    """Return the attempt as the student sees it; load its own revision if needed."""
    if attempt.revision_id != revision.id:
        own = await load_revision(uow, attempt.revision_id)
        test = find_test_block(own.content, attempt.block_id)
    return attempt_view(attempt, test)
