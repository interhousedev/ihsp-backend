"""LMS-12, UF-LMS-13: checkpoints, step history, restore and pruning."""

from app.modules.lms.application.authoring.views import StepDraftView
from app.modules.lms.domain.authoring.enums import RevisionKind
from app.modules.lms.domain.authoring.errors import (
    CoursePermissionError,
    RevisionNotFoundError,
    TitleInvalidError,
)
from app.modules.lms.infrastructure.authoring.uow import SqlAuthoringUnitOfWork
from app.modules.lms.infrastructure.orm import StepRevision as RevisionRow
from app.modules.lms.infrastructure.orm import TestAttempt as AttemptRow
from app.modules.lms.wiring_authoring import AuthoringServices
from app.shared.db.uow_testing import noop_audit_writer, noop_outbox_writer
from app.shared.ids import new_id
from tests.fakes.clock import FixedClock
from tests.lms.authoring.conftest import CourseFixture
from tests.lms.authoring.helpers import (
    count_revisions,
    revisions_of,
    seed_published,
    set_blocks,
    step_row,
    text_block,
)

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def _step(services: AuthoringServices, course: CourseFixture) -> StepDraftView:
    owner = course.team.owner
    section = await services.create_section.execute(owner, course.id, "Limits")
    return await services.create_step.execute(
        owner, course.id, section_id=section.id, title="Intro"
    )


async def _checkpoints(
    services: AuthoringServices,
    course: CourseFixture,
    clock: FixedClock,
    step: StepDraftView,
    count: int,
) -> StepDraftView:
    """Save `count` checkpoints with different content, one minute apart."""
    owner = course.team.owner
    for n in range(count):
        step = await set_blocks(services, owner, step, text_block(f"v{n}"))
        clock.advance(minutes=1)
        await services.save_checkpoint.execute(owner, step.step_id, f"cp {n}")
    return step


async def test_a_checkpoint_is_listed_in_the_history_with_its_label(
    services: AuthoringServices, course: CourseFixture, clock: FixedClock
) -> None:
    """UF-LMS-13: name a checkpoint, see it in History."""
    owner = course.team.owner
    step = await _step(services, course)
    step = await set_blocks(services, owner, step, text_block("draft 1"))

    saved = await services.save_checkpoint.execute(
        owner, step.step_id, "  before rewriting questions  "
    )
    history = await services.list_step_history.execute(owner, step.step_id)

    assert (saved.kind, saved.label, saved.published) == (
        "checkpoint",
        "before rewriting questions",
        False,
    )
    assert saved.created_by.id == owner.user_id
    assert [h.id for h in history] == [saved.id]


async def test_history_lists_published_states_and_hides_previews(
    services: AuthoringServices, course: CourseFixture, clock: FixedClock
) -> None:
    """LMS-12: previews do not appear; published states do."""
    owner = course.team.owner
    seeded = await seed_published(services, owner, course.id)
    clock.advance(minutes=1)
    await services.save_checkpoint.execute(owner, seeded.step_a.step_id, "same as live")
    edited = await set_blocks(services, owner, seeded.step_a, text_block("A2"))
    await services.ensure_preview_revision.execute(edited.step_id, owner)

    history = await services.list_step_history.execute(owner, seeded.step_a.step_id)

    assert [(h.kind, h.published) for h in history] == [("publish", True)]
    assert history[0].label == "same as live"


async def test_checkpoint_of_unchanged_content_reuses_the_revision_and_renames_it(
    services: AuthoringServices,
    course: CourseFixture,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    """README: on a hash conflict the existing row is reused and its label updated."""
    owner = course.team.owner
    step = await _step(services, course)
    first = await services.save_checkpoint.execute(owner, step.step_id, "one")

    second = await services.save_checkpoint.execute(owner, step.step_id, "two")

    assert second.id == first.id and second.label == "two"
    assert await count_revisions(sessionmaker_in_tx, step.step_id) == 1


async def test_restoring_a_checkpoint_puts_its_content_into_the_draft(
    services: AuthoringServices, course: CourseFixture, clock: FixedClock
) -> None:
    """UF-LMS-13 3: Restore puts a checkpoint into the draft, as a save."""
    owner = course.team.owner
    step = await _step(services, course)
    step = await set_blocks(services, owner, step, text_block("good"))
    checkpoint = await services.save_checkpoint.execute(owner, step.step_id, "good")
    step = await set_blocks(services, owner, step, text_block("bad rewrite"))

    restored = await services.restore_revision.execute(
        owner, step.step_id, checkpoint.id
    )

    assert restored.content.blocks[0].markdown == "good"
    assert restored.lock_version == step.lock_version + 1
    assert restored.updated_by is not None and restored.updated_by.id == owner.user_id


async def test_a_revision_of_another_step_cannot_be_restored(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """Revisions are scoped to their step."""
    owner = course.team.owner
    first = await _step(services, course)
    section = await services.create_section.execute(owner, course.id, "More")
    second = await services.create_step.execute(
        owner, course.id, section_id=section.id, title="Other"
    )
    foreign = await services.save_checkpoint.execute(owner, second.step_id, "other")

    with pytest.raises(RevisionNotFoundError):
        await services.restore_revision.execute(owner, first.step_id, foreign.id)
    with pytest.raises(RevisionNotFoundError):
        await services.restore_revision.execute(owner, first.step_id, new_id())


async def test_checkpoint_label_and_permission_are_checked(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """Labels have 1-120 characters; checkpoints need `edit`."""
    step = await _step(services, course)

    with pytest.raises(TitleInvalidError):
        await services.save_checkpoint.execute(course.team.owner, step.step_id, "  ")
    with pytest.raises(CoursePermissionError):
        await services.save_checkpoint.execute(course.team.tester, step.step_id, "x")
    with pytest.raises(CoursePermissionError):
        await services.list_step_history.execute(course.team.tester, step.step_id)


async def test_only_the_newest_20_checkpoints_are_kept(
    services: AuthoringServices,
    course: CourseFixture,
    clock: FixedClock,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    """UF-LMS-13 1a: with more than 20 checkpoints the oldest is removed."""
    step = await _step(services, course)

    step = await _checkpoints(services, course, clock, step, 23)

    history = await services.list_step_history.execute(course.team.owner, step.step_id)
    assert len(history) == 20
    assert [h.label for h in history][:2] == ["cp 22", "cp 21"]
    assert history[-1].label == "cp 3"
    assert await count_revisions(sessionmaker_in_tx, step.step_id) == 20


async def test_pruning_never_deletes_published_or_attempted_revisions(
    services: AuthoringServices,
    course: CourseFixture,
    clock: FixedClock,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    """README: pruning keeps revisions with `published_at` or used by an attempt."""
    owner = course.team.owner
    step = await _step(services, course)
    step = await set_blocks(services, owner, step, text_block("protected"))
    published = await services.save_checkpoint.execute(owner, step.step_id, "published")
    clock.advance(minutes=1)
    step = await set_blocks(services, owner, step, text_block("attempted"))
    attempted = await services.save_checkpoint.execute(owner, step.step_id, "attempted")
    async with sessionmaker_in_tx() as session:
        await session.execute(
            update(RevisionRow)
            .where(RevisionRow.id == published.id)
            .values(published_at=clock.now())
        )
        session.add(
            AttemptRow(
                user_id=new_id(),
                step_id=step.step_id,
                revision_id=attempted.id,
                block_id="b",
                attempt_no=1,
                variant={},
                max_score=1,
            )
        )
        await session.commit()

    step = await _checkpoints(services, course, clock, step, 25)

    kept = {r.id for r in await revisions_of(sessionmaker_in_tx, step.step_id)}
    assert published.id in kept and attempted.id in kept
    labels = [
        h.label for h in await services.list_step_history.execute(owner, step.step_id)
    ]
    assert len([x for x in labels if x and x.startswith("cp ")]) == 20


async def test_the_prune_job_trims_checkpoints_and_old_previews(
    services: AuthoringServices,
    course: CourseFixture,
    clock: FixedClock,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    """LMS-12: 20 checkpoints per step, 30 days of previews."""
    owner = course.team.owner
    step = await _step(services, course)
    step = await set_blocks(services, owner, step, text_block("preview me"))
    old_preview = await services.ensure_preview_revision.execute(step.step_id, owner)
    clock.advance(days=31)
    step = await set_blocks(services, owner, step, text_block("recent preview"))
    recent_preview = await services.ensure_preview_revision.execute(step.step_id, owner)
    async with SqlAuthoringUnitOfWork(
        sessionmaker_in_tx, noop_outbox_writer, noop_audit_writer
    ) as uow:
        for n in range(24):
            clock.advance(minutes=1)
            await uow.revisions.ensure(
                step_id=step.step_id,
                content={"title": "Intro", "blocks": [], "n": n},
                content_hash=f"hash-{n:03d}",
                kind=RevisionKind.CHECKPOINT,
                label=f"direct {n}",
                file_ids=[],
                created_by=owner.user_id,
                now=clock.now(),
            )
        await uow.commit()

    result = await services.prune_revisions.execute()

    ids = {r.id for r in await revisions_of(sessionmaker_in_tx, step.step_id)}
    assert (result.checkpoints, result.previews) == (4, 1)
    assert old_preview not in ids and recent_preview in ids
    kinds = [r.kind for r in await revisions_of(sessionmaker_in_tx, step.step_id)]
    assert kinds.count("checkpoint") == 20


async def test_seeded_helpers_report_the_live_revision(
    services: AuthoringServices,
    course: CourseFixture,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    """A publish revision is marked published and is never pruned."""
    owner = course.team.owner
    seeded = await seed_published(services, owner, course.id)

    row = await step_row(sessionmaker_in_tx, seeded.step_a.step_id)
    (revision,) = await revisions_of(sessionmaker_in_tx, seeded.step_a.step_id)

    assert revision.id == row.live_revision_id
    assert revision.kind == "publish" and revision.published_at is not None
