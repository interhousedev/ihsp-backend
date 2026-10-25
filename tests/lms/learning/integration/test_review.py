"""LMS-20, UF-LMS-15: reviewers see students and attempts and override scores."""

from app.modules.lms.domain.learning.errors import (
    AttemptNotFoundError,
    AttemptNotSubmittedError,
    CoursePermissionError,
    ScoreInvalidError,
)
from app.modules.lms.wiring_learning import LearningServices
from app.shared.actor import Actor
from app.shared.ids import new_id
from tests.fakes.clock import FixedClock
from tests.lms.learning.builders import (
    add_staff,
    content,
    publish_version,
    text_block,
)
from tests.lms.learning.scenarios import ONE_RIGHT, RIGHT, WRONG, quiz_course, take

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def test_reviewers_see_students_with_progress_and_attempts(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
    other_student: Actor,
    teacher: Actor,
    clock: FixedClock,
) -> None:
    """UF-LMS-15 1: students with progress and test results."""
    course, step = await quiz_course(maker, learning, student, with_text_step=True)
    await learning.enroll_in_course.execute(other_student, course.id)
    await add_staff(maker, course, teacher.user_id, permissions=["review"])
    await take(learning, student, step, WRONG)
    clock.advance(minutes=1)
    passed = await take(learning, student, step, RIGHT)

    students = await learning.list_course_students.execute(teacher, course.id)

    assert [s.user.last_name for s in students] == ["Other", "Student"]
    other, mine = students
    assert (other.progress_pct, other.attempts) == (0, [])
    assert mine.progress_pct == 50
    assert [(a.score, a.max_score, a.passed) for a in mine.attempts] == [
        (0.0, 3.0, False),
        (3.0, 3.0, True),
    ]
    assert mine.attempts[1].id == passed.id
    assert mine.attempts[1].step_id == step.step_id
    assert mine.attempts[1].block_id == "quiz"


async def test_listing_students_needs_the_review_permission(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
    teacher: Actor,
    lms_admin: Actor,
) -> None:
    """LMS-5, LMS-20, LMS-21: `review` or the LMS admin."""
    course, _ = await quiz_course(maker, learning, student)
    await add_staff(maker, course, teacher.user_id, permissions=["edit", "publish"])

    with pytest.raises(CoursePermissionError):
        await learning.list_course_students.execute(student, course.id)
    with pytest.raises(CoursePermissionError):
        await learning.list_course_students.execute(teacher, course.id)
    as_admin = await learning.list_course_students.execute(lms_admin, course.id)

    assert len(as_admin) == 1


async def test_progress_in_the_list_is_current_after_a_new_version(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
    teacher: Actor,
) -> None:
    """LMS-14: the list recomputes progress for the live version."""
    course, step = await quiz_course(maker, learning, student)
    await add_staff(maker, course, teacher.user_id, permissions=["review"])
    await take(learning, student, step, RIGHT)
    before = (await learning.list_course_students.execute(teacher, course.id))[0]

    await publish_version(
        maker,
        course,
        [("quiz", step.content), ("extra", content("Extra", text_block()))],
    )
    after = (await learning.list_course_students.execute(teacher, course.id))[0]

    assert (before.progress_pct, after.progress_pct) == (100, 50)
    assert before.completed_at is not None


async def test_a_reviewer_sees_the_variant_answers_and_revision_of_an_attempt(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """UF-LMS-15 2: the variant, the answers and the version it was taken on."""
    _, step = await quiz_course(maker, learning, student, show_answers="never")
    result = await take(learning, student, step, ONE_RIGHT)

    as_owner = await learning.get_attempt.execute(student, result.id)

    assert as_owner.review is None
    assert as_owner.user.last_name == "Student"
    assert as_owner.variant["question_ids"] == ["q1", "q2", "q3"]
    assert as_owner.answers == ONE_RIGHT
    assert as_owner.revision_id == step.revision_id
    assert as_owner.override_score is None
    assert as_owner.override_comment is None


async def test_reviewers_always_see_the_correct_answers(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
    teacher: Actor,
) -> None:
    """UF-LMS-15: show_answers limits students, not reviewers."""
    course, step = await quiz_course(maker, learning, student, show_answers="never")
    await add_staff(maker, course, teacher.user_id, permissions=["review"])
    result = await take(learning, student, step, ONE_RIGHT)

    seen = await learning.get_attempt.execute(teacher, result.id)

    assert seen.review is not None
    assert [item.correct for item in seen.review] == [True, False, False]
    assert seen.review[1].correct_answer == {"number": 4.0}


async def test_staff_without_review_cannot_read_other_peoples_attempts(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
    teacher: Actor,
) -> None:
    """LMS-20: reading attempts needs `review`."""
    course, step = await quiz_course(maker, learning, student)
    await add_staff(maker, course, teacher.user_id, permissions=["edit"])
    result = await take(learning, student, step, RIGHT)

    with pytest.raises(AttemptNotFoundError):
        await learning.get_attempt.execute(teacher, result.id)


async def test_an_attempt_without_a_result_cannot_be_read_yet(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """UF-LMS-04: an open attempt has no result."""
    _, step = await quiz_course(maker, learning, student)
    attempt = await learning.start_attempt.execute(
        student, step.step_id, "quiz", preview=False
    )

    with pytest.raises(AttemptNotSubmittedError):
        await learning.get_attempt.execute(student, attempt.id)


async def test_overriding_a_score_recomputes_passed_completion_and_progress(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
    teacher: Actor,
) -> None:
    """UF-LMS-15 3, LMS-20: the student's progress follows the reviewer's decision."""
    course, step = await quiz_course(maker, learning, student, with_text_step=True)
    await add_staff(maker, course, teacher.user_id, permissions=["review"])
    failed = await take(learning, student, step, ONE_RIGHT)
    assert failed.passed is False

    raised = await learning.override_score.execute(
        teacher, failed.id, 3.0, "A correct text answer did not match."
    )
    after_raise = await learning.get_step_view.execute(student, course.id, step.step_id)
    mine = await learning.list_my_courses.execute(student)
    lowered = await learning.override_score.execute(teacher, failed.id, 0.5, "Copied.")
    after_lower = await learning.get_step_view.execute(student, course.id, step.step_id)
    mine_after = await learning.list_my_courses.execute(student)

    assert (raised.score, raised.passed, raised.override_score) == (3.0, True, 3.0)
    assert raised.override_comment == "A correct text answer did not match."
    assert raised.review is not None
    assert after_raise.completed is True
    assert after_raise.blocks[0].best.score == 3.0
    assert mine.enrolled[0].progress_pct == 50
    assert (lowered.score, lowered.passed) == (0.5, False)
    assert after_lower.completed is False
    assert mine_after.enrolled[0].progress_pct == 0


async def test_the_student_sees_the_override_in_the_attempt(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
    teacher: Actor,
) -> None:
    """LMS-20: the owner reads the reviewer's score and comment."""
    course, step = await quiz_course(maker, learning, student)
    await add_staff(maker, course, teacher.user_id, permissions=["review"])
    result = await take(learning, student, step, WRONG)

    await learning.override_score.execute(teacher, result.id, 2.0, "Partly right.")
    seen = await learning.get_attempt.execute(student, result.id)

    assert (seen.score, seen.override_score) == (2.0, 2.0)
    assert seen.override_comment == "Partly right."


@pytest.mark.parametrize("score", [-0.5, 3.5, float("nan")])
async def test_a_score_outside_zero_to_max_is_refused(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
    teacher: Actor,
    score: float,
) -> None:
    """LMS-20: the override stays within the points of the attempt."""
    course, step = await quiz_course(maker, learning, student)
    await add_staff(maker, course, teacher.user_id, permissions=["review"])
    result = await take(learning, student, step, WRONG)

    with pytest.raises(ScoreInvalidError):
        await learning.override_score.execute(teacher, result.id, score, "No.")


async def test_only_reviewers_can_override(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
    teacher: Actor,
) -> None:
    """LMS-20: students cannot change their own score; `edit` is not `review`."""
    course, step = await quiz_course(maker, learning, student)
    await add_staff(maker, course, teacher.user_id, permissions=["edit"])
    result = await take(learning, student, step, WRONG)

    with pytest.raises(CoursePermissionError):
        await learning.override_score.execute(student, result.id, 3.0, "Please.")
    with pytest.raises(CoursePermissionError):
        await learning.override_score.execute(teacher, result.id, 3.0, "Hm.")


async def test_an_unknown_or_open_attempt_cannot_be_overridden(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
    teacher: Actor,
) -> None:
    """LMS-20: only submitted attempts have a score to override."""
    course, step = await quiz_course(maker, learning, student)
    await add_staff(maker, course, teacher.user_id, permissions=["review"])
    attempt = await learning.start_attempt.execute(
        student, step.step_id, "quiz", preview=False
    )

    with pytest.raises(AttemptNotFoundError):
        await learning.override_score.execute(teacher, new_id(), 1.0, "?")
    with pytest.raises(AttemptNotSubmittedError):
        await learning.override_score.execute(teacher, attempt.id, 1.0, "Too early.")


async def test_the_lms_admin_can_override_without_a_staff_row(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
    lms_admin: Actor,
) -> None:
    """LMS-21: the LMS admin manages every course."""
    _, step = await quiz_course(maker, learning, student)
    result = await take(learning, student, step, WRONG)

    reviewed = await learning.override_score.execute(lms_admin, result.id, 3.0, "Ok.")

    assert reviewed.passed is True
