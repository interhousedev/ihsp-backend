"""LMS-14, LMS-19, UF-LMS-03: what the learner screen needs to show progress.

Per block "passed" marks and points for the step strip and the lesson header,
and points and passed steps per course for the sidebar and the course page.
"""

from app.modules.lms.application.learning.views import (
    LearningFlashcardsBlockView,
    LearningQuizBlockView,
    LearningTextBlockView,
)
from app.modules.lms.wiring_learning import LearningServices
from app.shared.actor import Actor
from app.shared.srs import Rating
from tests.lms.learning.builders import (
    SeededCourse,
    add_staff,
    cards,
    choice,
    content,
    quiz,
    seed_course,
    text_block,
)
from tests.lms.learning.scenarios import (
    ONE_RIGHT,
    QUESTIONS,
    RIGHT,
    quiz_course,
    take,
)

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def mixed_course(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> SeededCourse:
    """A course with a text step, a mixed step and a quiz-only step; enrolled."""
    course = await seed_course(
        maker,
        steps=[
            ("read", content("Reading", text_block())),
            (
                "mixed",
                content(
                    "Mixed", text_block("t1"), quiz("quiz", QUESTIONS), cards("deck")
                ),
            ),
            (
                "exam",
                content("Exam", quiz("exam", [choice("e1", correct=["a"], points=4)])),
            ),
        ],
    )
    await learning.enroll_in_course.execute(student, course.id)
    return course


async def test_a_new_step_has_nothing_passed_and_shows_its_points(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """Strip squares start empty; the header knows the points of the step."""
    course = await mixed_course(maker, learning, student)

    view = await learning.get_step_view.execute(
        student, course.id, course.step("mixed").step_id
    )

    assert (view.blocks_total, view.blocks_passed) == (3, 0)
    assert (view.points_total, view.points_earned) == (3.0, 0.0)
    assert [block.passed for block in view.blocks] == [False, False, False]
    quiz_view = view.blocks[1]
    assert isinstance(quiz_view, LearningQuizBlockView)
    assert (quiz_view.points_total, quiz_view.points_earned) == (3.0, 0.0)


async def test_a_text_block_is_passed_once_the_step_is_viewed(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """Text steps pass by viewing them, as in the sidebar's green check."""
    course = await mixed_course(maker, learning, student)
    step = course.step("mixed")

    await learning.mark_step_viewed.execute(student, step.step_id)
    view = await learning.get_step_view.execute(student, course.id, step.step_id)

    text = view.blocks[0]
    assert isinstance(text, LearningTextBlockView)
    assert text.passed is True
    assert (view.blocks_total, view.blocks_passed) == (3, 1)
    assert view.completed is False


async def test_a_test_block_is_passed_only_by_a_passing_attempt(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """A failed attempt earns its points but does not pass the block."""
    course, step = await quiz_course(maker, learning, student)

    await take(learning, student, step, ONE_RIGHT)
    failed = await learning.get_step_view.execute(student, course.id, step.step_id)
    await take(learning, student, step, RIGHT)
    passed = await learning.get_step_view.execute(student, course.id, step.step_id)

    first, second = failed.blocks[0], passed.blocks[0]
    assert isinstance(first, LearningQuizBlockView)
    assert isinstance(second, LearningQuizBlockView)
    assert (first.passed, first.points_earned, failed.points_earned) == (
        False,
        1.0,
        1.0,
    )
    assert (second.passed, second.points_earned, passed.points_earned) == (
        True,
        3.0,
        3.0,
    )
    assert (passed.blocks_total, passed.blocks_passed, passed.points_total) == (
        1,
        1,
        3.0,
    )


async def test_points_come_from_the_best_attempt_not_the_last(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """A worse retry never takes earned points away."""
    course, step = await quiz_course(maker, learning, student)

    await take(learning, student, step, RIGHT)
    await take(learning, student, step, {})
    view = await learning.get_step_view.execute(student, course.id, step.step_id)

    assert view.points_earned == 3.0


async def test_a_reviewers_score_counts_as_earned_points(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
    teacher: Actor,
) -> None:
    """LMS-20: an override replaces the graded score in the points."""
    course, step = await quiz_course(maker, learning, student)
    await add_staff(maker, course, teacher.user_id, permissions=["review"])
    failed = await take(learning, student, step, ONE_RIGHT)

    await learning.override_score.execute(teacher, failed.id, 2.5, "Partly right.")
    view = await learning.get_step_view.execute(student, course.id, step.step_id)

    assert view.points_earned == 2.5


async def test_a_flash_card_block_is_passed_when_every_card_was_studied(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """The block turns green after all of its cards were rated once."""
    course = await mixed_course(maker, learning, student)
    step_id = course.step("mixed").step_id

    await learning.review_card.execute(student, step_id, "c1", Rating.EASY)
    await learning.review_card.execute(student, step_id, "c2", Rating.EASY)
    partly = await learning.get_step_view.execute(student, course.id, step_id)
    await learning.review_card.execute(student, step_id, "c3", Rating.EASY)
    fully = await learning.get_step_view.execute(student, course.id, step_id)

    before, after = partly.blocks[2], fully.blocks[2]
    assert isinstance(before, LearningFlashcardsBlockView)
    assert isinstance(after, LearningFlashcardsBlockView)
    assert (before.passed, after.passed) == (False, True)


async def test_the_course_page_totals_points_and_passed_steps(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """The sidebar shows "earned/total" points and the outline marks each step."""
    course = await mixed_course(maker, learning, student)
    await learning.mark_step_viewed.execute(student, course.step("read").step_id)
    await take(learning, student, course.step("mixed"), RIGHT, block_id="quiz")

    page = await learning.get_course_page.execute(student, course.slug)

    assert page.enrolled is True
    assert page.points_total == 7.0
    assert page.points_earned == 3.0
    assert page.steps_completed == 2
    steps = {step.title: step for step in page.outline[0].steps}
    assert [(s.points_total, s.points_earned) for s in steps.values()] == [
        (0.0, 0.0),
        (3.0, 3.0),
        (4.0, 0.0),
    ]


async def test_a_visitor_sees_the_points_of_the_course_but_none_earned(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
    other_student: Actor,
) -> None:
    """The promo page shows the size of the course; progress values stay empty."""
    course = await mixed_course(maker, learning, student)

    page = await learning.get_course_page.execute(other_student, course.slug)

    assert page.enrolled is False
    assert page.points_total == 7.0
    assert page.points_earned is None
    assert page.steps_completed is None
    assert all(step.points_earned is None for step in page.outline[0].steps)
    assert [step.points_total for step in page.outline[0].steps] == [0.0, 3.0, 4.0]


async def test_progress_numbers_of_other_students_stay_apart(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
    other_student: Actor,
) -> None:
    """Earned points are the viewer's own."""
    course = await mixed_course(maker, learning, student)
    await learning.enroll_in_course.execute(other_student, course.id)
    await take(
        learning,
        student,
        course.step("exam"),
        {"e1": {"option_ids": ["e1-a"]}},
        block_id="exam",
    )

    mine = await learning.get_course_page.execute(student, course.slug)
    theirs = await learning.get_course_page.execute(other_student, course.slug)

    assert (mine.points_earned, theirs.points_earned) == (4.0, 0.0)
