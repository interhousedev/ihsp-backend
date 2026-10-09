"""LMS-AI: the staff side of a course workspace (``LmsWorkspace``)."""

from collections.abc import Callable
from uuid import UUID

from app.modules.lms.domain.authoring.enums import Visibility
from app.modules.lms.domain.authoring.errors import StepNotFoundError
from app.modules.lms.domain.authoring.outline import RemoveStep
from app.modules.lms.domain.authoring.permissions import PERMISSION_ORDER
from app.modules.lms.infrastructure.orm.enrollment import Enrollment
from app.modules.lms.wiring_authoring import AuthoringServices
from app.shared.actor import Actor, Role
from app.shared.ids import new_id
from tests.fakes.lms.identity import FakeIdentityDirectory
from tests.lms.authoring.conftest import CourseFixture
from tests.lms.authoring.helpers import (
    cards_block,
    publish,
    quiz_block,
    seed_published,
    set_blocks,
    single_question,
    step_row,
    text_block,
)

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# - - - Who may open the workspace - - -


async def test_staff_get_the_permissions_of_their_row_in_canonical_order(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """The workspace reads `edit` and `view_drafts`; the rest is reported as is."""
    team = course.team
    workspace = services.workspace

    owner = await workspace.course_access(team.owner.user_id, course.id)
    teacher = await workspace.course_access(team.teacher.user_id, course.id)
    tester = await workspace.course_access(team.tester.user_id, course.id)

    assert owner is not None and teacher is not None and tester is not None
    assert owner.permissions == PERMISSION_ORDER
    assert teacher.permissions == ("edit", "publish", "review", "view_drafts")
    assert tester.permissions == ("view_drafts",)
    assert (owner.course_id, owner.title, owner.description) == (
        course.id,
        "Calculus",
        "",
    )
    assert (owner.can_write, owner.can_read) == (True, True)
    assert (teacher.can_write, teacher.can_read) == (True, True)
    assert (tester.can_write, tester.can_read) == (False, True)


async def test_a_reviewer_is_staff_but_can_neither_read_nor_write_the_workspace(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """`review` alone is a staff row without `edit` or `view_drafts`."""
    access = await services.workspace.course_access(
        course.team.reviewer.user_id, course.id
    )

    assert access is not None
    assert access.permissions == ("review",)
    assert (access.can_write, access.can_read) == (False, False)


async def test_an_lms_admin_holds_every_permission_without_a_staff_row(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """The same rule as `CourseAccess.is_admin`, read from the identity roles."""
    access = await services.workspace.course_access(
        course.team.admin.user_id, course.id
    )

    assert access is not None
    assert access.permissions == PERMISSION_ORDER
    assert access.can_write


async def test_admin_beats_a_narrow_staff_row(
    services: AuthoringServices,
    course: CourseFixture,
    identity: FakeIdentityDirectory,
    make_actor: Callable[..., Actor],
) -> None:
    """A tester who is also an LMS admin can edit."""
    both = make_actor(Role.TEACHER)
    identity.add_user(
        "both", user_id=both.user_id, roles=[Role.TEACHER, Role.LMS_ADMIN]
    )
    await services.add_course_staff.execute(
        course.team.admin, course.id, login="both", role="Tester", permissions=None
    )

    access = await services.workspace.course_access(both.user_id, course.id)

    assert access is not None and access.permissions == PERMISSION_ORDER


async def test_strangers_students_and_unknown_courses_get_nothing(
    services: AuthoringServices,
    course: CourseFixture,
    identity: FakeIdentityDirectory,
    make_actor: Callable[..., Actor],
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    """Not on the staff, enrolled as a student, unknown course or user: None."""
    student = make_actor(Role.STUDENT)
    identity.add_user("student", user_id=student.user_id, roles=[Role.STUDENT])
    async with sessionmaker_in_tx() as session:
        session.add(
            Enrollment(course_id=course.id, user_id=student.user_id, via="self")
        )
        await session.commit()
    workspace = services.workspace

    assert (
        await workspace.course_access(course.team.outsider.user_id, course.id) is None
    )
    assert await workspace.course_access(student.user_id, course.id) is None
    assert await workspace.course_access(new_id(), course.id) is None
    assert await workspace.course_access(course.team.owner.user_id, new_id()) is None
    assert await workspace.course_access(course.team.admin.user_id, new_id()) is None


async def test_the_title_and_description_are_those_of_the_draft(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """An unpublished rename already shows in the workspace."""
    owner = course.team.owner
    await services.update_course_meta.execute(
        owner,
        course.id,
        title="Calculus 2",
        description="Series and integrals",
        lock_version=course.course.lock_version,
    )

    access = await services.workspace.course_access(owner.user_id, course.id)

    assert access is not None
    assert (access.title, access.description) == ("Calculus 2", "Series and integrals")


async def test_removing_a_person_from_the_staff_ends_their_access(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """The access is read on every call, so a removed teacher loses it at once."""
    teacher = course.team.teacher
    assert await services.workspace.course_access(teacher.user_id, course.id)

    await services.remove_course_staff.execute(
        course.team.admin, course.id, teacher.user_id
    )

    assert await services.workspace.course_access(teacher.user_id, course.id) is None


# - - - The outline - - -


async def test_the_brief_lists_the_draft_outline_with_ids_and_titles(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """Sections and steps in order, plus the draft sequence and the draft meta."""
    owner = course.team.owner
    first = await services.create_section.execute(owner, course.id, "Limits")
    second = await services.create_section.execute(owner, course.id, "Derivatives")
    a = await services.create_step.execute(
        owner, course.id, section_id=first.id, title="Idea"
    )
    b = await services.create_step.execute(
        owner, course.id, section_id=first.id, title="Rules"
    )
    draft = await services.get_course_draft.execute(owner, course.id)

    brief = await services.workspace.course_brief(course.id)

    assert brief is not None
    assert (brief.course_id, brief.title, brief.draft_seq) == (
        course.id,
        "Calculus",
        draft.draft_seq,
    )
    assert [(s.section_id, s.title) for s in brief.sections] == [
        (first.id, "Limits"),
        (second.id, "Derivatives"),
    ]
    assert [(s.step_id, s.title) for s in brief.sections[0].steps] == [
        (a.step_id, "Idea"),
        (b.step_id, "Rules"),
    ]
    assert brief.sections[1].steps == ()


async def test_the_brief_leaves_out_steps_removed_from_the_draft_outline(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """A removed but still published step is a ghost in the editor, not in the brief."""
    owner = course.team.owner
    seeded = await seed_published(services, owner, course.id)
    await services.apply_outline_ops.execute(
        owner,
        course.id,
        [RemoveStep(op="remove_step", step_id=seeded.step_b.step_id)],
        lock_version=None,
    )

    brief = await services.workspace.course_brief(course.id)

    assert brief is not None
    assert [s.step_id for s in brief.sections[0].steps] == [seeded.step_a.step_id]


async def test_the_brief_of_an_unknown_course_is_none(
    services: AuthoringServices,
) -> None:
    """The caller has just checked the access, so an unknown course is simply None."""
    assert await services.workspace.course_brief(new_id()) is None


# - - - The draft text of a step - - -


async def _step(
    services: AuthoringServices, actor: Actor, course_id: UUID, title: str = "Cells"
) -> UUID:
    section = await services.create_section.execute(actor, course_id, "Biology")
    step = await services.create_step.execute(
        actor, course_id, section_id=section.id, title=title
    )
    return step.step_id


async def test_a_draft_step_is_read_as_text_blocks_and_flash_cards_never_tests(
    services: AuthoringServices,
    course: CourseFixture,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    """LMS-17: the same text as for students; the quiz and its answers stay out."""
    owner = course.team.owner
    step_id = await _step(services, owner, course.id)
    step = await services.get_step_draft.execute(owner, step_id)
    await set_blocks(
        services,
        owner,
        step,
        text_block("# Cells\n\nThe cell is the unit of life."),
        cards_block(),
        quiz_block(single_question("Secret quiz question?")),
        text_block("Mitochondria make ATP."),
    )

    result = await services.workspace.draft_step_text(course.id, step_id)

    assert (result.course_id, result.step_id) == (course.id, step_id)
    assert (result.course_title, result.title) == ("Calculus", "Cells")
    assert result.text == (
        "# Cells\n\nThe cell is the unit of life.\n\n"
        "Q: Power rule\nA: n·xⁿ⁻¹\n\n"
        "Mitochondria make ATP."
    )
    assert "Secret" not in result.text and "None of the above" not in result.text
    assert [result.text[s : s + 7] for s in result.block_starts] == [
        "# Cells",
        "Q: Powe",
        "Mitocho",
    ]
    assert (
        result.revision_id == (await step_row(sessionmaker_in_tx, step_id)).draft_hash
    )


async def test_a_changed_draft_changes_the_revision_id(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """The draft hash marks a notebook source as outdated; it is stable otherwise."""
    owner = course.team.owner
    step_id = await _step(services, owner, course.id)
    step = await services.get_step_draft.execute(owner, step_id)
    first = await set_blocks(services, owner, step, text_block("One"))
    before = await services.workspace.draft_step_text(course.id, step_id)
    again = await services.workspace.draft_step_text(course.id, step_id)

    await set_blocks(services, owner, first, text_block("Two"))
    after = await services.workspace.draft_step_text(course.id, step_id)

    assert before.revision_id == again.revision_id
    assert after.revision_id != before.revision_id
    assert (before.text, after.text) == ("One", "Two")


async def test_the_draft_text_is_the_draft_not_the_published_step(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """Students read the live revision; the workspace reads what is being written."""
    owner = course.team.owner
    seeded = await seed_published(services, owner, course.id)
    await set_blocks(services, owner, seeded.step_a, text_block("A2, unpublished"))

    result = await services.workspace.draft_step_text(course.id, seeded.step_a.step_id)

    assert result.text == "A2, unpublished"


async def test_a_step_without_text_gives_an_empty_text(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """A step with only a test has nothing to export."""
    owner = course.team.owner
    step_id = await _step(services, owner, course.id)
    step = await services.get_step_draft.execute(owner, step_id)
    await set_blocks(services, owner, step, quiz_block(single_question()))

    result = await services.workspace.draft_step_text(course.id, step_id)

    assert (result.text, result.block_starts) == ("", ())


async def test_a_step_of_another_course_or_an_unknown_step_is_not_found(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """The step must belong to the course the source was added for."""
    admin = course.team.admin
    other = await services.create_course.execute(
        admin, title="Algebra", slug="algebra", visibility=Visibility.PUBLIC
    )
    foreign = await _step(services, admin, other.id)

    with pytest.raises(StepNotFoundError):
        await services.workspace.draft_step_text(course.id, foreign)
    with pytest.raises(StepNotFoundError):
        await services.workspace.draft_step_text(course.id, new_id())
    own = await services.workspace.draft_step_text(other.id, foreign)
    assert own.step_id == foreign


async def test_publishing_does_not_change_the_draft_revision_id(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """The draft hash follows the content, so a publish alone keeps a source fresh."""
    owner = course.team.owner
    seeded = await seed_published(services, owner, course.id)
    step_id = seeded.step_a.step_id
    await set_blocks(services, owner, seeded.step_a, text_block("A2"))
    before = await services.workspace.draft_step_text(course.id, step_id)

    await publish(services, owner, course.id)
    after = await services.workspace.draft_step_text(course.id, step_id)

    assert after.text == "A2" and after.revision_id == before.revision_id
