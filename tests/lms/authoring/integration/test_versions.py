"""LMS-10, LMS-11, UF-LMS-11, UF-LMS-12: browse, compare, restore, discard."""

from uuid import uuid4

from app.modules.lms.domain.authoring.errors import (
    CoursePermissionError,
    NoLiveVersionError,
    VersionNotFoundError,
)
from app.modules.lms.domain.authoring.outline import RemoveStep
from app.modules.lms.wiring_authoring import AuthoringServices
from tests.lms.authoring.conftest import CourseFixture
from tests.lms.authoring.helpers import (
    publish,
    seed_published,
    set_blocks,
    text_block,
)

import pytest


async def test_versions_are_listed_newest_first_with_author_and_summary(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """UF-LMS-11 1: number, publisher, note and what changed."""
    owner, teacher = course.team.owner, course.team.teacher
    seeded = await seed_published(services, owner, course.id)
    await set_blocks(services, teacher, seeded.step_a, text_block("A2"))
    await publish(services, teacher, course.id, note="Fixed A")

    versions = await services.list_versions.execute(course.team.reviewer, course.id)

    assert [v.number for v in versions] == [2, 1]
    assert versions[0].published_by.id == teacher.user_id
    assert versions[0].note == "Fixed A"
    assert versions[0].changes.changed == 1


async def test_a_version_opens_with_its_title_and_outline_as_published(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """UF-LMS-11 2: a version is shown exactly as students saw it."""
    owner = course.team.owner
    seeded = await seed_published(services, owner, course.id)
    await services.apply_outline_ops.execute(
        owner,
        course.id,
        [RemoveStep(op="remove_step", step_id=seeded.step_b.step_id)],
        lock_version=None,
    )
    await publish(services, owner, course.id)

    v1 = await services.get_version.execute(owner, course.id, 1)
    v2 = await services.get_version.execute(owner, course.id, 2)

    assert v1.meta.title == "Calculus"
    assert [(s.title) for s in v1.outline[0].steps] == ["Step A", "Step B"]
    assert [(s.title) for s in v2.outline[0].steps] == ["Step A"]
    assert all(s.badge is None for s in v1.outline[0].steps)


async def test_compare_two_versions_step_by_step(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """UF-LMS-11 3: the outline shows which steps differ."""
    owner = course.team.owner
    seeded = await seed_published(services, owner, course.id)
    await set_blocks(services, owner, seeded.step_a, text_block("A2"))
    added = await services.create_step.execute(
        owner, course.id, section_id=seeded.section_id, title="Step C"
    )
    await services.apply_outline_ops.execute(
        owner,
        course.id,
        [RemoveStep(op="remove_step", step_id=seeded.step_b.step_id)],
        lock_version=None,
    )
    await publish(services, owner, course.id)

    forward = await services.compare_versions.execute(owner, course.id, 1, 2)
    backward = await services.compare_versions.execute(owner, course.id, 2, 1)

    assert (forward.a, forward.b) == (1, 2)
    assert {s.step_id: s.change for s in forward.steps} == {
        seeded.step_a.step_id: "changed",
        added.step_id: "added",
        seeded.step_b.step_id: "removed",
    }
    assert {s.step_id: s.change for s in backward.steps} == {
        seeded.step_a.step_id: "changed",
        added.step_id: "removed",
        seeded.step_b.step_id: "added",
    }
    same = await services.compare_versions.execute(owner, course.id, 2, 2)
    assert {s.change for s in same.steps} == {"same"}


async def test_unknown_version_is_not_found(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """A missing number is a 404."""
    owner = course.team.owner
    await seed_published(services, owner, course.id)

    with pytest.raises(VersionNotFoundError):
        await services.get_version.execute(owner, course.id, 9)
    with pytest.raises(VersionNotFoundError):
        await services.compare_versions.execute(owner, course.id, 1, 9)


async def test_people_outside_the_team_cannot_browse_versions(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """Versions are for course staff."""
    await seed_published(services, course.team.owner, course.id)

    with pytest.raises(CoursePermissionError):
        await services.list_versions.execute(course.team.outsider, course.id)


async def test_restoring_an_old_version_makes_pending_changes_equal_the_difference(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """LMS-11, UF-LMS-12: restore copies a version into the draft."""
    owner = course.team.owner
    seeded = await seed_published(services, owner, course.id)
    await set_blocks(services, owner, seeded.step_a, text_block("A2"))
    added = await services.create_step.execute(
        owner, course.id, section_id=seeded.section_id, title="Step C"
    )
    await publish(services, owner, course.id)

    restored = await services.restore_version.execute(owner, course.id, 1)

    pending = await services.get_pending_changes.execute(owner, course.id)
    assert {s.step_id: s.change for s in pending.steps} == {
        seeded.step_a.step_id: "changed",
        added.step_id: "removed",
    }
    assert restored.pending_count == 2
    step_a = await services.get_step_draft.execute(owner, seeded.step_a.step_id)
    assert step_a.content.blocks[0].markdown == "A1"
    assert step_a.status == "changed"
    assert [s.title for s in restored.outline[0].steps if s.badge != "removed"] == [
        "Step A",
        "Step B",
    ]


async def test_publishing_a_restored_version_creates_a_new_version_and_keeps_history(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """LMS-11: history is append-only; version 3 equals version 1 in content."""
    owner = course.team.owner
    seeded = await seed_published(services, owner, course.id)
    await set_blocks(services, owner, seeded.step_a, text_block("A2"))
    await publish(services, owner, course.id)
    await services.restore_version.execute(owner, course.id, 1)

    v3 = await publish(services, owner, course.id, note="Back to version 1")

    assert v3.number == 3
    assert [
        v.number for v in await services.list_versions.execute(owner, course.id)
    ] == [3, 2, 1]
    compared = await services.compare_versions.execute(owner, course.id, 1, 3)
    assert {s.change for s in compared.steps} == {"same"}
    changed = await services.compare_versions.execute(owner, course.id, 2, 3)
    assert {s.step_id: s.change for s in changed.steps}[
        seeded.step_a.step_id
    ] == "changed"


async def test_restore_puts_removed_steps_back_into_the_outline(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """README: steps that no longer exist in the draft outline are re-added."""
    owner = course.team.owner
    seeded = await seed_published(services, owner, course.id)
    await services.apply_outline_ops.execute(
        owner,
        course.id,
        [RemoveStep(op="remove_step", step_id=seeded.step_b.step_id)],
        lock_version=None,
    )
    await publish(services, owner, course.id)

    restored = await services.restore_version.execute(owner, course.id, 1)

    assert [s.step_id for s in restored.outline[0].steps] == [
        seeded.step_a.step_id,
        seeded.step_b.step_id,
    ]
    assert [s.badge for s in restored.outline[0].steps] == [None, "new"]


async def test_restore_needs_the_edit_permission_and_an_existing_version(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """Testers cannot restore; unknown versions are 404."""
    await seed_published(services, course.team.owner, course.id)

    with pytest.raises(CoursePermissionError):
        await services.restore_version.execute(course.team.tester, course.id, 1)
    with pytest.raises(VersionNotFoundError):
        await services.restore_version.execute(course.team.owner, course.id, 5)


async def test_discarding_the_course_returns_every_part_of_the_draft_to_live(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """LMS-10, UF-LMS-12 3: discard resets meta, outline and steps."""
    owner = course.team.owner
    seeded = await seed_published(services, owner, course.id)
    draft = await services.get_course_draft.execute(owner, course.id)
    await services.update_course_meta.execute(
        owner,
        course.id,
        title="Renamed",
        description="x",
        lock_version=draft.lock_version,
    )
    await set_blocks(services, owner, seeded.step_a, text_block("A2"))
    await services.create_step.execute(
        owner, course.id, section_id=seeded.section_id, title="Step C"
    )

    discarded = await services.discard_course.execute(owner, course.id)

    pending = await services.get_pending_changes.execute(owner, course.id)
    assert discarded.title == "Calculus"
    assert [s.title for s in discarded.outline[0].steps] == ["Step A", "Step B"]
    assert pending.steps == [] and not pending.outline_changed
    assert discarded.pending_count == 0
    step_a = await services.get_step_draft.execute(owner, seeded.step_a.step_id)
    assert step_a.content.blocks[0].markdown == "A1"


async def test_discarding_a_never_published_course_is_refused(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """There is no live version to go back to."""
    with pytest.raises(NoLiveVersionError):
        await services.discard_course.execute(course.team.owner, course.id)


async def test_discarding_one_step_keeps_the_others_pending(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """LMS-10: pending changes can be discarded per step."""
    owner = course.team.owner
    seeded = await seed_published(services, owner, course.id)
    await set_blocks(services, owner, seeded.step_a, text_block("A2"))
    await set_blocks(services, owner, seeded.step_b, text_block("B2"))

    reset = await services.discard_step.execute(owner, seeded.step_a.step_id)

    pending = await services.get_pending_changes.execute(owner, course.id)
    assert reset.status == "unchanged"
    assert reset.content.blocks[0].markdown == "A1"
    assert [s.step_id for s in pending.steps] == [seeded.step_b.step_id]


async def test_discarding_a_new_step_is_refused_and_unknown_steps_are_not_found(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """A step never published has no live revision to return to."""
    owner = course.team.owner
    section = await services.create_section.execute(owner, course.id, "Limits")
    step = await services.create_step.execute(
        owner, course.id, section_id=section.id, title="Intro"
    )

    with pytest.raises(NoLiveVersionError):
        await services.discard_step.execute(owner, step.step_id)
    with pytest.raises(Exception) as caught:
        await services.discard_step.execute(owner, uuid4())
    assert caught.value.code == "lms/step-not-found"


async def test_step_diff_shows_live_and_draft_content(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """UF-LMS-10 1: each changed step has a diff with the live version."""
    owner = course.team.owner
    seeded = await seed_published(services, owner, course.id)
    await set_blocks(services, owner, seeded.step_a, text_block("A2"))
    section = await services.create_section.execute(owner, course.id, "More")
    fresh = await services.create_step.execute(
        owner, course.id, section_id=section.id, title="Fresh"
    )

    diff = await services.get_step_diff.execute(owner, seeded.step_a.step_id)
    new_diff = await services.get_step_diff.execute(owner, fresh.step_id)

    assert diff.live is not None and diff.live.blocks[0].markdown == "A1"
    assert diff.draft.blocks[0].markdown == "A2"
    assert new_diff.live is None
