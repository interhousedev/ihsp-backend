"""LMS-4, LMS-14, UF-LMS-01, UF-LMS-05: the course page, its staff and its marks."""

from app.modules.lms.domain.learning.errors import CourseNotFoundError
from app.modules.lms.infrastructure.orm.course import Course
from app.modules.lms.wiring_learning import LearningServices
from app.shared.actor import Actor
from tests.lms.learning.builders import (
    add_staff,
    content,
    publish_version,
    quiz,
    seed_course,
    text_block,
)
from tests.lms.learning.fakes.identity import FakeIdentityDirectory

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

STEPS = [
    ("s1", content("Intro", text_block())),
    ("s2", content("Reading", text_block())),
    ("s3", content("Quiz", quiz())),
]


async def test_the_page_shows_staff_on_the_page_in_order_with_their_roles(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    identity: FakeIdentityDirectory,
    student: Actor,
) -> None:
    """LMS-4: name and role of each staff member shown on the page."""
    course = await seed_course(maker, steps=STEPS)
    kalandarova = identity.add(first_name="Gavxar", last_name="Kalandarova")
    brastilov = identity.add(first_name="Aleksey", last_name="Brastilov")
    hidden = identity.add(first_name="Hidden", last_name="Staff")
    await add_staff(maker, course, kalandarova.id, role="Teacher", position=2)
    await add_staff(maker, course, brastilov.id, role="Support", position=1)
    await add_staff(maker, course, hidden.id, role="Tester", show_on_page=False)

    page = await learning.get_course_page.execute(student, course.slug)

    assert [(s.user.last_name, s.role) for s in page.staff] == [
        ("Brastilov", "Support"),
        ("Kalandarova", "Teacher"),
    ]
    assert page.title == "Algebra"
    assert page.description == "About Algebra"
    assert page.steps_count == 3
    assert page.enrolled is False
    assert page.can_edit is False


async def test_a_visitor_sees_the_outline_without_completion_marks(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """LMS-4: the outline of the live version; completion only for enrolled students."""
    course = await seed_course(maker, steps=STEPS)

    page = await learning.get_course_page.execute(student, course.slug)

    assert [(s.title, s.completed) for s in page.outline[0].steps] == [
        ("Intro", None),
        ("Reading", None),
        ("Quiz", None),
    ]
    assert page.outline[0].title == "Section"


async def test_an_enrolled_student_sees_completed_steps_and_progress(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """LMS-4, LMS-19: completion flags and the progress percentage."""
    course = await seed_course(maker, steps=STEPS)
    await learning.enroll_in_course.execute(student, course.id)

    await learning.mark_step_viewed.execute(student, course.step("s1").step_id)
    page = await learning.get_course_page.execute(student, course.slug)

    assert [s.completed for s in page.outline[0].steps] == [True, False, False]
    assert page.progress_pct == 33
    assert page.enrolled is True


async def test_staff_with_edit_can_edit_and_the_lms_admin_always_can(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    teacher: Actor,
    lms_admin: Actor,
    student: Actor,
) -> None:
    """LMS-5, LMS-21: `can_edit` follows the `edit` permission."""
    course = await seed_course(maker, steps=STEPS)
    await add_staff(maker, course, teacher.user_id, permissions=["edit", "review"])

    as_teacher = await learning.get_course_page.execute(teacher, course.slug)
    as_admin = await learning.get_course_page.execute(lms_admin, course.slug)
    as_student = await learning.get_course_page.execute(student, course.slug)

    assert (as_teacher.can_edit, as_admin.can_edit, as_student.can_edit) == (
        True,
        True,
        False,
    )


async def test_an_unknown_course_is_not_found(
    learning: LearningServices, student: Actor
) -> None:
    """LMS-3: a missing slug is a not found error."""
    with pytest.raises(CourseNotFoundError):
        await learning.get_course_page.execute(student, "nope")


async def test_an_invite_only_course_is_hidden_until_the_student_joins(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """LMS-3, UF-LMS-02: members only."""
    course = await seed_course(
        maker, visibility="invite", invite_code="ABCDEFGHJK", steps=STEPS
    )
    with pytest.raises(CourseNotFoundError):
        await learning.get_course_page.execute(student, course.slug)

    await learning.join_course.execute(student, "ABCDEFGHJK")
    page = await learning.get_course_page.execute(student, course.slug)

    assert page.enrolled is True


async def test_an_archived_course_stays_open_for_enrolled_students(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """LMS-14: students keep their course when it is archived."""
    course = await seed_course(maker, steps=STEPS)
    await learning.enroll_in_course.execute(student, course.id)
    async with maker() as session:
        await session.execute(
            update(Course).where(Course.id == course.id).values(status="archived")
        )
        await session.commit()

    page = await learning.get_course_page.execute(student, course.slug)

    assert page.enrolled is True


async def test_staff_see_a_course_that_was_never_published_with_an_empty_outline(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    teacher: Actor,
    student: Actor,
) -> None:
    """LMS-9: students see nothing before the first publish, staff see the shell."""
    course = await seed_course(maker, publish=False)
    await add_staff(maker, course, teacher.user_id, permissions=["edit"])

    page = await learning.get_course_page.execute(teacher, course.slug)

    assert page.outline == []
    assert page.steps_count == 0
    with pytest.raises(CourseNotFoundError):
        await learning.get_course_page.execute(student, course.slug)


async def test_the_page_marks_new_and_changed_steps_since_the_last_visit(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """UF-LMS-05, LMS-14: updated courses mark what is new or changed, once."""
    course = await seed_course(maker, steps=STEPS)
    await learning.enroll_in_course.execute(student, course.id)
    first = await learning.get_course_page.execute(student, course.slug)
    old_s1, old_s2 = course.step("s1"), course.step("s2")

    await publish_version(
        maker,
        course,
        [
            ("s1", content("Intro", text_block(markdown="Rewritten."))),
            ("s2", old_s2.content),
            *STEPS[2:],
            ("s4", content("Extra", text_block())),
        ],
    )
    second = await learning.get_course_page.execute(student, course.slug)
    third = await learning.get_course_page.execute(student, course.slug)

    assert first.changed_since_last_visit == []
    assert set(second.changed_since_last_visit) == {
        old_s1.step_id,
        course.step("s4").step_id,
    }
    badges = {s.title: s.badge for s in second.outline[0].steps}
    assert badges == {
        "Intro": "changed",
        "Reading": None,
        "Quiz": None,
        "Extra": "new",
    }
    assert third.changed_since_last_visit == []
