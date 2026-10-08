"""LMS-7, LMS-9, LMS-13, LMS-14, UF-LMS-10: pending changes and publishing."""

from app.modules.lms.domain.authoring.errors import (
    CoursePermissionError,
    DraftChangedError,
    NothingToPublishError,
)
from app.modules.lms.domain.authoring.outline import MoveStep, RemoveStep
from app.modules.lms.wiring_authoring import AuthoringServices
from tests.lms.authoring.conftest import CourseFixture
from tests.lms.authoring.helpers import (
    count_revisions,
    publish,
    revisions_of,
    seed_published,
    set_blocks,
    step_row,
    text_block,
)

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def test_pending_lists_added_changed_and_removed_steps(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """LMS-7: pending changes are the difference with the live version."""
    owner = course.team.owner
    seeded = await seed_published(services, owner, course.id)
    changed = await set_blocks(services, owner, seeded.step_a, text_block("A2"))
    added = await services.create_step.execute(
        owner, course.id, section_id=seeded.section_id, title="Step C"
    )
    await services.apply_outline_ops.execute(
        owner,
        course.id,
        [RemoveStep(op="remove_step", step_id=seeded.step_b.step_id)],
        lock_version=None,
    )

    pending = await services.get_pending_changes.execute(owner, course.id)

    by_step = {s.step_id: s.change for s in pending.steps}
    assert by_step == {
        changed.step_id: "changed",
        added.step_id: "added",
        seeded.step_b.step_id: "removed",
    }
    assert pending.outline_changed
    draft = await services.get_course_draft.execute(owner, course.id)
    badges = {s.step_id: s.badge for sec in draft.outline for s in sec.steps}
    assert badges == {
        seeded.step_a.step_id: "changed",
        added.step_id: "new",
        seeded.step_b.step_id: "removed",
    }
    assert draft.pending_count == 3
    assert draft.live_version == 1


async def test_a_published_course_with_no_edits_has_nothing_pending(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """After publishing the draft equals the live version."""
    owner = course.team.owner
    await seed_published(services, owner, course.id)

    pending = await services.get_pending_changes.execute(owner, course.id)
    draft = await services.get_course_draft.execute(owner, course.id)

    assert pending.steps == [] and not pending.outline_changed
    assert draft.pending_count == 0
    assert all(s.badge is None for sec in draft.outline for s in sec.steps)


async def test_publish_creates_version_1_and_points_the_course_at_it(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """LMS-9: publishing creates a version students see at once."""
    owner = course.team.owner
    seeded = await seed_published(services, owner, course.id)

    versions = await services.list_versions.execute(owner, course.id)

    assert seeded.version.number == 1
    assert seeded.version.note == "First version"
    assert seeded.version.published_by.id == owner.user_id
    assert seeded.version.changes.added == 2
    assert seeded.version.changes.outline_changed
    assert [v.number for v in versions] == [1]
    assert (await services.get_course_draft.execute(owner, course.id)).live_version == 1


async def test_publish_stores_revisions_only_for_changed_steps(
    services: AuthoringServices,
    course: CourseFixture,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    """README: unchanged steps are shared between versions."""
    owner = course.team.owner
    seeded = await seed_published(services, owner, course.id)
    a_before = await step_row(sessionmaker_in_tx, seeded.step_a.step_id)
    await set_blocks(services, owner, seeded.step_b, text_block("B2"))

    v2 = await publish(services, owner, course.id)

    a_after = await step_row(sessionmaker_in_tx, seeded.step_a.step_id)
    b_after = await step_row(sessionmaker_in_tx, seeded.step_b.step_id)
    assert v2.number == 2
    assert (v2.changes.added, v2.changes.changed, v2.changes.removed) == (0, 1, 0)
    assert a_after.live_revision_id == a_before.live_revision_id
    assert await count_revisions(sessionmaker_in_tx, seeded.step_a.step_id) == 1
    assert await count_revisions(sessionmaker_in_tx, seeded.step_b.step_id) == 2
    assert b_after.live_hash == b_after.draft_hash
    compared = await services.compare_versions.execute(owner, course.id, 1, 2)
    assert {s.title: s.revision_a == s.revision_b for s in compared.steps} == {
        "Step A": True,
        "Step B": False,
    }


async def test_publishing_content_equal_to_an_older_revision_reuses_it(
    services: AuthoringServices,
    course: CourseFixture,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    """README: a revision with the same hash is reused, not duplicated."""
    owner = course.team.owner
    seeded = await seed_published(services, owner, course.id)
    first = (await step_row(sessionmaker_in_tx, seeded.step_a.step_id)).live_revision_id
    edited = await set_blocks(services, owner, seeded.step_a, text_block("A2"))
    await publish(services, owner, course.id)
    assert first is not None
    reverted = await services.restore_revision.execute(
        owner, seeded.step_a.step_id, first
    )

    await publish(services, owner, course.id)

    row = await step_row(sessionmaker_in_tx, reverted.step_id)
    assert row.live_revision_id == first
    assert edited.step_id == reverted.step_id
    assert await count_revisions(sessionmaker_in_tx, reverted.step_id) == 2


async def test_publish_refuses_a_draft_that_changed_after_review(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """LMS-13, UF-LMS-10 3a: publishing is refused if the draft moved."""
    owner, teacher = course.team.owner, course.team.teacher
    seeded = await seed_published(services, owner, course.id)
    await set_blocks(services, owner, seeded.step_a, text_block("A2"))
    reviewed = await services.get_pending_changes.execute(owner, course.id)
    await set_blocks(services, teacher, seeded.step_b, text_block("B2"))

    with pytest.raises(DraftChangedError) as caught:
        await services.publish_course.execute(
            owner, course.id, draft_seq=reviewed.draft_seq, note=None
        )

    assert caught.value.code == "lms/draft-changed"
    assert caught.value.status == 409
    again = await publish(services, owner, course.id)
    assert (again.changes.changed) == 2


async def test_publish_with_nothing_pending_is_refused(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """UF-LMS-10 1a: nothing to publish."""
    owner = course.team.owner
    seeded = await seed_published(services, owner, course.id)
    draft = await services.get_course_draft.execute(owner, course.id)

    with pytest.raises(NothingToPublishError):
        await services.publish_course.execute(
            owner, course.id, draft_seq=draft.draft_seq, note=None
        )
    assert seeded.version.number == 1


async def test_publish_needs_the_publish_permission(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """LMS-5: reviewers and testers cannot publish."""
    owner = course.team.owner
    section = await services.create_section.execute(owner, course.id, "Limits")
    assert section.id
    draft = await services.get_course_draft.execute(owner, course.id)

    for actor in (course.team.reviewer, course.team.tester, course.team.outsider):
        with pytest.raises(CoursePermissionError):
            await services.publish_course.execute(
                actor, course.id, draft_seq=draft.draft_seq, note=None
            )


async def test_changing_only_the_title_is_publishable(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """The meta is part of the outline hash."""
    owner = course.team.owner
    await seed_published(services, owner, course.id)
    draft = await services.get_course_draft.execute(owner, course.id)
    await services.update_course_meta.execute(
        owner,
        course.id,
        title="Calculus I",
        description="Intro",
        lock_version=draft.lock_version,
    )

    version = await publish(services, owner, course.id, note="  Renamed  ")

    detail = await services.get_version.execute(owner, course.id, version.number)
    assert version.note == "Renamed"
    assert version.changes.outline_changed and version.changes.changed == 0
    assert (detail.meta.title, detail.meta.description) == ("Calculus I", "Intro")


async def test_removed_step_leaves_the_live_version_and_can_come_back(
    services: AuthoringServices,
    course: CourseFixture,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    """README: removing a step only removes it from the outline; history survives."""
    owner = course.team.owner
    seeded = await seed_published(services, owner, course.id)
    b_id = seeded.step_b.step_id
    original = (await step_row(sessionmaker_in_tx, b_id)).live_revision_id
    await services.apply_outline_ops.execute(
        owner,
        course.id,
        [RemoveStep(op="remove_step", step_id=b_id)],
        lock_version=None,
    )

    v2 = await publish(services, owner, course.id)

    row = await step_row(sessionmaker_in_tx, b_id)
    assert v2.changes.removed == 1
    assert (row.live_revision_id, row.live_hash) == (None, None)
    in_v2 = await services.get_version.execute(owner, course.id, 2)
    assert [s.step_id for s in in_v2.outline[0].steps] == [seeded.step_a.step_id]
    after = await services.get_course_draft.execute(owner, course.id)
    assert [s.badge for s in after.outline[0].steps] == [None]

    await services.apply_outline_ops.execute(
        owner,
        course.id,
        [
            MoveStep(
                op="move_step",
                step_id=b_id,
                to_section_id=seeded.section_id,
                position=1,
            )
        ],
        lock_version=None,
    )
    pending = await services.get_pending_changes.execute(owner, course.id)
    await publish(services, owner, course.id)

    assert [(s.step_id, s.change) for s in pending.steps] == [(b_id, "added")]
    assert (await step_row(sessionmaker_in_tx, b_id)).live_revision_id == original
    assert len(await revisions_of(sessionmaker_in_tx, b_id)) == 1


async def test_unpublished_removed_steps_do_not_show_as_ghosts_but_published_ones_do(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """LMS-7: the outline shows a removed step with the `removed` badge."""
    owner = course.team.owner
    seeded = await seed_published(services, owner, course.id)
    await services.apply_outline_ops.execute(
        owner,
        course.id,
        [RemoveStep(op="remove_step", step_id=seeded.step_b.step_id)],
        lock_version=None,
    )

    draft = await services.get_course_draft.execute(owner, course.id)

    assert [(s.title, s.badge) for s in draft.outline[0].steps] == [
        ("Step A", None),
        ("Step B", "removed"),
    ]
