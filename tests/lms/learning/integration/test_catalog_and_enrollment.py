"""LMS-1, LMS-3, LMS-19, UF-LMS-01, UF-LMS-02: catalog, enrollment and invite codes."""

from app.modules.lms.domain.learning.errors import (
    CourseNotFoundError,
    InviteNotValidError,
)
from app.modules.lms.wiring_learning import LearningServices
from app.shared.actor import Actor
from app.shared.base_error import RateLimitedError
from app.shared.ids import new_id
from tests.lms.learning.builders import add_staff, content, seed_course, text_block

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

ONE_STEP = [("s1", content("One", text_block()))]
CODE = "ABCDEFGHJK"


async def test_the_catalog_lists_only_published_active_public_courses(
    maker: async_sessionmaker[AsyncSession], learning: LearningServices
) -> None:
    """LMS-3, UF-LMS-01: published public courses only."""
    await seed_course(maker, slug="public", title="Public", steps=ONE_STEP)
    await seed_course(
        maker, slug="invite", visibility="invite", invite_code=CODE, steps=ONE_STEP
    )
    await seed_course(maker, slug="draft", publish=False)
    await seed_course(maker, slug="old", status="archived", steps=ONE_STEP)

    cards = await learning.list_catalog.execute()

    assert [card.slug for card in cards] == ["public"]
    assert cards[0].steps_count == 1
    assert cards[0].progress_pct is None
    assert cards[0].visibility == "public"
    assert cards[0].updated_at is not None


async def test_the_catalog_search_matches_titles_and_escapes_wildcards(
    maker: async_sessionmaker[AsyncSession], learning: LearningServices
) -> None:
    """UF-LMS-01: a query filters by title; user input is not a LIKE pattern."""
    await seed_course(maker, slug="alg", title="Algebra", steps=ONE_STEP)
    await seed_course(maker, slug="geo", title="Geometry", steps=ONE_STEP)

    found = await learning.list_catalog.execute(query="ALGE")
    wildcard = await learning.list_catalog.execute(query="%")

    assert [card.slug for card in found] == ["alg"]
    assert wildcard == []


async def test_enrolling_adds_the_course_to_my_courses_with_zero_progress(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """UF-LMS-01: the course appears in My courses with 0 % progress."""
    course = await seed_course(maker, steps=ONE_STEP)

    page = await learning.enroll_in_course.execute(student, course.id)
    mine = await learning.list_my_courses.execute(student)

    assert page.enrolled is True
    assert page.progress_pct == 0
    assert [card.slug for card in mine.enrolled] == [course.slug]
    assert mine.enrolled[0].progress_pct == 0
    assert mine.managed == []


async def test_enrolling_twice_keeps_one_enrollment(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """LMS-19: enrollment is idempotent."""
    course = await seed_course(maker, steps=ONE_STEP)

    await learning.enroll_in_course.execute(student, course.id)
    again = await learning.enroll_in_course.execute(student, course.id)
    mine = await learning.list_my_courses.execute(student)

    assert again.enrolled is True
    assert len(mine.enrolled) == 1


@pytest.mark.parametrize(
    "options",
    [
        {"visibility": "invite", "invite_code": CODE},
        {"status": "archived"},
        {"publish": False},
    ],
    ids=["invite-only", "archived", "unpublished"],
)
async def test_only_published_active_public_courses_can_be_enrolled_in(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
    options: dict,
) -> None:
    """LMS-3: public courses only; other courses look missing."""
    course = await seed_course(maker, steps=ONE_STEP, **options)

    with pytest.raises(CourseNotFoundError):
        await learning.enroll_in_course.execute(student, course.id)


async def test_an_unknown_course_cannot_be_enrolled_in(
    learning: LearningServices, student: Actor
) -> None:
    """LMS-3: a missing id is a not found error."""
    with pytest.raises(CourseNotFoundError):
        await learning.enroll_in_course.execute(student, new_id())


async def test_a_valid_invite_code_enrolls_in_an_invite_only_course(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """UF-LMS-02: joining with the code enrolls the student."""
    course = await seed_course(
        maker, visibility="invite", invite_code=CODE, steps=ONE_STEP
    )

    page = await learning.join_course.execute(student, f" {CODE} ")
    mine = await learning.list_my_courses.execute(student)

    assert page.id == course.id
    assert page.enrolled is True
    assert page.visibility == "invite"
    assert [card.id for card in mine.enrolled] == [course.id]


async def test_a_wrong_or_rotated_code_is_not_found(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """UF-LMS-02 1a: a wrong code is 'Invite not valid'."""
    await seed_course(maker, visibility="invite", invite_code=CODE, steps=ONE_STEP)

    with pytest.raises(InviteNotValidError):
        await learning.join_course.execute(student, "WRONGCODE1")


async def test_a_code_of_a_public_course_does_not_join(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """LMS-3: a stale code on a course that became public is not an invite."""
    await seed_course(maker, visibility="public", invite_code=CODE, steps=ONE_STEP)

    with pytest.raises(InviteNotValidError):
        await learning.join_course.execute(student, CODE)


async def test_joining_is_limited_to_ten_tries_an_hour(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """LMS-3: joining is rate limited (`lms-join:{user}` 10 per hour)."""
    await seed_course(maker, visibility="invite", invite_code=CODE, steps=ONE_STEP)
    for _ in range(10):
        with pytest.raises(InviteNotValidError):
            await learning.join_course.execute(student, "WRONGCODE1")

    with pytest.raises(RateLimitedError) as caught:
        await learning.join_course.execute(student, CODE)

    assert caught.value.params["retry_after"] > 0


async def test_my_courses_lists_managed_courses_for_staff_and_all_for_the_admin(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    teacher: Actor,
    lms_admin: Actor,
    student: Actor,
) -> None:
    """LMS-21: staff see their courses, the LMS admin sees every course."""
    mine = await seed_course(maker, slug="mine", title="Mine", steps=ONE_STEP)
    await seed_course(maker, slug="other", title="Other", publish=False)
    await add_staff(maker, mine, teacher.user_id, permissions=["edit"])

    as_teacher = await learning.list_my_courses.execute(teacher)
    as_admin = await learning.list_my_courses.execute(lms_admin)
    as_student = await learning.list_my_courses.execute(student)

    assert [card.slug for card in as_teacher.managed] == ["mine"]
    assert as_teacher.managed[0].steps_count == 1
    assert [card.slug for card in as_admin.managed] == ["mine", "other"]
    assert as_student.managed == []
