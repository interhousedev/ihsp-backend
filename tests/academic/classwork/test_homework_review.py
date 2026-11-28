"""Teacher review of homework submissions and the linked temporary mark."""

import datetime as dt
from uuid import UUID, uuid4

from app.modules.academic.domain.classwork.errors import (
    NotLessonTeacherError,
    ReviewCommentRequiredError,
    SubmissionNotFoundError,
)
from app.shared.actor import Actor
from tests.academic.classwork.conftest import Env
from tests.academic.classwork.world import add_lesson, local

import pytest

FRIDAY = dt.date(2026, 10, 9)
MONDAY = dt.date(2026, 10, 12)


async def _lesson(env: Env) -> UUID:
    env.clock.set(local(FRIDAY, 12))
    return await add_lesson(
        env.maker,
        env.world,
        day=FRIDAY,
        period=1,
        homework_text="read",
        homework_due_date=MONDAY,
        homework_due_auto=False,
        homework_accept_submissions=True,
    )


async def _submit(env: Env, lesson: UUID, student: Actor) -> UUID:
    """Submit one file as the student; return the submission id."""
    await env.services.submit_homework.execute(
        lesson, student, [env.files.add(student.user_id)], None
    )
    listed = await env.services.list_homework_submissions.execute(lesson, env.teacher)
    row = next(
        s for s in listed["students"] if s["student"]["id"] == str(student.user_id)
    )
    return UUID(row["id"])


async def _marks(env: Env, lesson: UUID) -> dict[UUID, int]:
    listed = await env.services.list_lesson_temporary_marks.execute(lesson, env.teacher)
    return {v.mark.student_id: v.mark.value for v in listed}


async def test_grade_creates_linked_mark_and_return_deletes_it(env: Env) -> None:
    lesson = await _lesson(env)
    aziz = env.student("aziz")
    submission = await _submit(env, lesson, aziz)
    review = env.services.review_homework_submission

    row = await review.execute(submission, env.teacher, action="grade", grade=4)
    assert row["review_status"] == "graded" and row["grade"] == 4
    assert (await _marks(env, lesson)) == {aziz.user_id: 4}

    await review.execute(submission, env.teacher, action="grade", grade=5)
    assert (await _marks(env, lesson)) == {aziz.user_id: 5}

    with pytest.raises(ReviewCommentRequiredError):
        await review.execute(submission, env.teacher, action="return")
    row = await review.execute(
        submission, env.teacher, action="return", comment=" redo "
    )
    assert row["review_status"] == "returned" and row["grade"] is None
    assert row["teacher_comment"] == "redo"
    assert (await _marks(env, lesson)) == {}


async def test_manual_mark_is_kept_and_not_linked(env: Env) -> None:
    lesson = await _lesson(env)
    aziz = env.student("aziz")
    submission = await _submit(env, lesson, aziz)
    await env.services.set_temporary_mark.execute(
        lesson, aziz.user_id, env.teacher, value=3
    )
    review = env.services.review_homework_submission

    await review.execute(submission, env.teacher, action="grade", grade=5)
    assert (await _marks(env, lesson)) == {aziz.user_id: 3}

    await review.execute(submission, env.teacher, action="return", comment="redo")
    assert (await _marks(env, lesson)) == {aziz.user_id: 3}
    await env.services.clear_homework_review.execute(submission, env.teacher)
    assert (await _marks(env, lesson)) == {aziz.user_id: 3}


async def test_clear_review_goes_pending_and_deletes_linked_mark(env: Env) -> None:
    lesson = await _lesson(env)
    aziz = env.student("aziz")
    submission = await _submit(env, lesson, aziz)
    await env.services.review_homework_submission.execute(
        submission, env.teacher, action="grade", grade=4
    )

    await env.services.clear_homework_review.execute(submission, env.teacher)

    row = await env.services.get_staff_homework_submission.execute(
        submission, env.teacher
    )
    assert row["review_status"] == "pending" and row["grade"] is None
    assert (await _marks(env, lesson)) == {}


async def test_other_teacher_and_unknown_submission_are_refused(env: Env) -> None:
    lesson = await _lesson(env)
    submission = await _submit(env, lesson, env.student("aziz"))
    s = env.services

    with pytest.raises(NotLessonTeacherError):
        await s.get_staff_homework_submission.execute(submission, env.other_teacher)
    with pytest.raises(NotLessonTeacherError):
        await s.review_homework_submission.execute(
            submission, env.other_teacher, action="grade", grade=5
        )
    with pytest.raises(NotLessonTeacherError):
        await s.clear_homework_review.execute(submission, env.other_teacher)
    with pytest.raises(SubmissionNotFoundError):
        await s.get_staff_homework_submission.execute(uuid4(), env.teacher)
    assert (await _marks(env, lesson)) == {}


async def test_board_lists_lessons_with_counts_and_switches(env: Env) -> None:
    lesson = await _lesson(env)
    await _submit(env, lesson, env.student("aziz"))
    options = await env.services.journal_options.execute(env.teacher)
    option = options[0]

    board = await env.services.homework_board.execute(
        env.teacher,
        UUID(option["subject"]["id"]),
        option["audience_key"],
        only="to_review",
    )

    item = next(i for i in board["lessons"] if i["lesson_id"] == str(lesson))
    assert item["accept_submissions"] is True
    assert item["homework"]["source"] == "teacher"
    assert item["counts"]["submitted"] == 1 and item["counts"]["to_review"] == 1
    assert set(board["settings"]) == {"accept_by_default", "notify_on_submission"}
