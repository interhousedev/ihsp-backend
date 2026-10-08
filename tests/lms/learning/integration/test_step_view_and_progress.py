"""LMS-14, LMS-17, LMS-19, UF-LMS-03, UF-LMS-05: reading steps and progress."""

from app.modules.lms.domain.learning.errors import (
    CourseNotFoundError,
    NotEnrolledError,
    StepNotFoundError,
)
from app.modules.lms.infrastructure.orm.enrollment import Enrollment
from app.modules.lms.wiring_learning import LearningServices
from app.shared.actor import Actor
from app.shared.ids import new_id
from tests.lms.learning.builders import (
    add_staff,
    cards,
    content,
    publish_version,
    quiz,
    seed_course,
    text_block,
)
from tests.lms.learning.helpers import FORBIDDEN_KEYS, keys_of
from tests.lms.learning.scenarios import QUESTIONS, RIGHT, quiz_course, take

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def enroll(learning: LearningServices, actor: Actor, course_id: object) -> None:
    """Enroll through the public use case."""
    await learning.enroll_in_course.execute(actor, course_id)  # type: ignore[arg-type]


async def test_a_step_without_tests_is_completed_by_opening_it(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """LMS-19, UF-LMS-03: opened and no tests -> completed, progress updates."""
    course = await seed_course(
        maker,
        steps=[
            ("s1", content("One", text_block())),
            ("s2", content("Two", text_block())),
        ],
    )
    await enroll(learning, student, course.id)

    viewed = await learning.mark_step_viewed.execute(student, course.step("s1").step_id)
    mine = await learning.list_my_courses.execute(student)

    assert viewed.completed is True
    assert viewed.viewed_at is not None
    assert mine.enrolled[0].progress_pct == 50


async def test_a_step_with_a_test_is_not_completed_by_opening_it(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """LMS-19: tests must be passed."""
    course, step = await quiz_course(maker, learning, student)

    viewed = await learning.mark_step_viewed.execute(student, step.step_id)

    assert viewed.completed is False


async def test_a_flash_card_only_step_is_completed_by_opening_it(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """LMS-19: 'or when opened if it has none' (no test blocks)."""
    course = await seed_course(maker, steps=[("s1", content("Cards", cards()))])
    await enroll(learning, student, course.id)

    viewed = await learning.mark_step_viewed.execute(student, course.step("s1").step_id)

    assert viewed.completed is True


async def test_opening_a_step_twice_keeps_it_completed(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """LMS-14: completion is never taken back by a later view."""
    course = await seed_course(maker, steps=[("s1", content("One", text_block()))])
    await enroll(learning, student, course.id)

    await learning.mark_step_viewed.execute(student, course.step("s1").step_id)
    again = await learning.mark_step_viewed.execute(student, course.step("s1").step_id)

    assert again.completed is True


async def test_only_enrolled_students_and_staff_can_open_steps(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
    other_student: Actor,
    teacher: Actor,
) -> None:
    """LMS-19: steps are for enrolled students; staff may read them too."""
    course = await seed_course(maker, steps=[("s1", content("One", text_block()))])
    step_id = course.step("s1").step_id
    await enroll(learning, student, course.id)
    await add_staff(maker, course, teacher.user_id, permissions=["edit"])

    own = await learning.get_step_view.execute(student, course.id, step_id)
    as_staff = await learning.get_step_view.execute(teacher, course.id, step_id)
    with pytest.raises(NotEnrolledError):
        await learning.get_step_view.execute(other_student, course.id, step_id)
    with pytest.raises(NotEnrolledError):
        await learning.mark_step_viewed.execute(other_student, step_id)

    assert own.title == as_staff.title == "One"
    assert own.preview is False


async def test_a_step_of_another_course_or_an_unknown_step_is_not_found(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """LMS-2: steps are addressed inside their course."""
    course = await seed_course(maker, steps=[("s1", content("One", text_block()))])
    await enroll(learning, student, course.id)

    with pytest.raises(CourseNotFoundError):
        await learning.get_step_view.execute(
            student, new_id(), course.step("s1").step_id
        )
    with pytest.raises(StepNotFoundError):
        await learning.get_step_view.execute(student, course.id, new_id())


async def test_the_student_step_view_never_contains_correct_answers(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """LMS-17: no correct options, answer configs or explanations before submitting."""
    course = await seed_course(
        maker,
        steps=[
            ("s1", content("Mixed", text_block(), quiz("quiz", QUESTIONS), cards()))
        ],
    )
    await enroll(learning, student, course.id)

    view = await learning.get_step_view.execute(
        student, course.id, course.step("s1").step_id
    )

    body = view.model_dump(mode="json")
    assert not FORBIDDEN_KEYS & keys_of(body)
    assert [block["type"] for block in body["blocks"]] == ["text", "test", "flashcards"]
    test_block = body["blocks"][1]
    assert test_block["rules"] == {
        "questions": 3,
        "attempts_left": None,
        "time_limit_sec": None,
        "passing_score_pct": 60.0,
    }
    assert test_block["best"] is None
    assert test_block["open_attempt_id"] is None
    assert body["blocks"][2]["cards_count"] == 3
    assert body["blocks"][2]["due"] == 3
    assert view.revision_id == course.step("s1").revision_id


async def test_the_step_view_shows_my_best_attempt_and_the_attempts_left(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """UF-LMS-04: the block shows the rules, the attempts left and my best result."""
    course, step = await quiz_course(
        maker, learning, student, max_attempts=3, show_answers="never"
    )
    await take(learning, student, step, RIGHT)

    view = await learning.get_step_view.execute(student, course.id, step.step_id)

    block = view.blocks[0]
    assert block.rules.attempts_left == 2
    assert block.best is not None
    assert (block.best.score, block.best.max_score, block.best.passed) == (
        3.0,
        3.0,
        True,
    )
    assert block.best.review is None
    assert view.completed is True


async def test_progress_drops_when_a_version_adds_a_step_but_completed_steps_stay(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """LMS-14, UF-LMS-05: new steps count toward progress; nothing is wiped."""
    one, two = content("One", text_block()), content("Two", text_block())
    course = await seed_course(maker, steps=[("s1", one), ("s2", two)])
    await enroll(learning, student, course.id)
    await learning.mark_step_viewed.execute(student, course.step("s1").step_id)
    await learning.mark_step_viewed.execute(student, course.step("s2").step_id)
    before = (await learning.list_my_courses.execute(student)).enrolled[0]

    await publish_version(
        maker,
        course,
        [("s1", one), ("s2", two), ("s3", content("Three", text_block()))],
    )
    after = (await learning.list_my_courses.execute(student)).enrolled[0]
    old_step = await learning.get_step_view.execute(
        student, course.id, course.step("s1").step_id
    )

    assert before.progress_pct == 100
    assert after.progress_pct == 67
    assert after.steps_count == 3
    assert old_step.completed is True
    async with maker() as session:
        row = await session.scalar(
            select(Enrollment).where(Enrollment.user_id == student.user_id)
        )
    assert row is not None
    assert row.completed_at is not None


async def test_a_step_removed_from_the_outline_is_not_readable(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """LMS-14: removing a step only removes it from the outline."""
    one, two = content("One", text_block()), content("Two", text_block())
    course = await seed_course(maker, steps=[("s1", one), ("s2", two)])
    await enroll(learning, student, course.id)
    removed = course.step("s2").step_id

    await publish_version(maker, course, [("s1", one)])

    with pytest.raises(StepNotFoundError):
        await learning.get_step_view.execute(student, course.id, removed)


async def test_a_new_revision_is_what_students_read_after_publishing(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """LMS-9: students see a new version right away."""
    course = await seed_course(maker, steps=[("s1", content("Old", text_block()))])
    await enroll(learning, student, course.id)
    step_id = course.step("s1").step_id
    old = await learning.get_step_view.execute(student, course.id, step_id)

    await publish_version(
        maker, course, [("s1", content("New", text_block(markdown="Fresh.")))]
    )
    new = await learning.get_step_view.execute(student, course.id, step_id)

    assert (old.title, new.title) == ("Old", "New")
    assert new.revision_id != old.revision_id
    assert new.blocks[0].markdown == "Fresh."  # type: ignore[union-attr]
