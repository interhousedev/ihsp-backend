"""LMS-8, UF-LMS-09: staff preview attempts on the draft never count."""

from app.modules.lms.domain.learning.errors import (
    CoursePermissionError,
    PreviewAttemptError,
)
from app.modules.lms.infrastructure.orm.step_state import StepState
from app.modules.lms.wiring_learning import LearningServices
from app.shared.actor import Actor
from tests.lms.learning.builders import (
    SeededCourse,
    SeededStep,
    add_preview_revision,
    add_staff,
    content,
    number_question,
    quiz,
)
from tests.lms.learning.fakes.preview_revisions import FakePreviewRevisions
from tests.lms.learning.scenarios import RIGHT, quiz_course, take

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

DRAFT = content(
    "Quiz (draft)",
    quiz("quiz", [number_question("q9", value=1)], max_attempts=1, cooldown_sec=600),
)


async def prepared(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    previews: FakePreviewRevisions,
    tester: Actor,
    *,
    permissions: tuple[str, ...] = ("view_drafts",),
    **config: object,
) -> tuple[SeededCourse, SeededStep]:
    """A course with a live quiz, a tester on its staff and a frozen draft revision."""
    course, step = await quiz_course(maker, learning, None, **config)
    await add_staff(maker, course, tester.user_id, permissions=permissions)
    revision = await add_preview_revision(maker, step, DRAFT, tester.user_id)
    previews.revisions[step.step_id] = revision
    return course, step


async def test_a_tester_takes_a_preview_attempt_on_the_frozen_draft(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    previews: FakePreviewRevisions,
    teacher: Actor,
) -> None:
    """LMS-8, UF-LMS-09 2: the tester sees the pending test, not the live one."""
    _, step = await prepared(maker, learning, previews, teacher)

    attempt = await learning.start_attempt.execute(
        teacher, step.step_id, "quiz", preview=True
    )
    await learning.save_answers.execute(teacher, attempt.id, {"q9": {"number": 1}})
    result = await learning.submit_attempt.execute(teacher, attempt.id)

    assert [q.id for q in attempt.questions] == ["q9"]
    assert previews.calls == [(step.step_id, teacher.user_id)]
    assert (result.score, result.max_score, result.passed) == (1.0, 1.0, True)


async def test_preview_attempts_have_no_limit_and_no_pause(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    previews: FakePreviewRevisions,
    teacher: Actor,
) -> None:
    """LMS-8: the draft says one attempt and a 10 minute pause; previews ignore both."""
    _, step = await prepared(maker, learning, previews, teacher)

    first = await learning.start_attempt.execute(
        teacher, step.step_id, "quiz", preview=True
    )
    await learning.submit_attempt.execute(teacher, first.id)
    second = await learning.start_attempt.execute(
        teacher, step.step_id, "quiz", preview=True
    )

    assert (first.attempt_no, second.attempt_no) == (1, 2)


async def test_preview_attempts_do_not_count_toward_the_real_attempts_limit(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    previews: FakePreviewRevisions,
    teacher: Actor,
) -> None:
    """LMS-8: a tester who is also a student still has all real attempts."""
    course, step = await prepared(maker, learning, previews, teacher, max_attempts=1)
    await learning.enroll_in_course.execute(teacher, course.id)
    preview = await learning.start_attempt.execute(
        teacher, step.step_id, "quiz", preview=True
    )
    await learning.submit_attempt.execute(teacher, preview.id)

    real = await take(learning, teacher, step, RIGHT)
    view = await learning.get_step_view.execute(teacher, course.id, step.step_id)

    assert real.passed is True
    assert view.blocks[0].rules.attempts_left == 0
    assert view.blocks[0].best.id == real.id


async def test_preview_attempts_leave_no_progress_and_no_review_rows(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    previews: FakePreviewRevisions,
    teacher: Actor,
) -> None:
    """LMS-8: previews never write StepState and are not listed to reviewers."""
    course, step = await prepared(
        maker, learning, previews, teacher, permissions=("view_drafts", "review")
    )
    attempt = await learning.start_attempt.execute(
        teacher, step.step_id, "quiz", preview=True
    )
    await learning.save_answers.execute(teacher, attempt.id, {"q9": {"number": 1}})
    await learning.submit_attempt.execute(teacher, attempt.id)

    listed = await learning.list_course_students.execute(teacher, course.id)
    async with maker() as session:
        states = (
            await session.scalars(
                select(StepState).where(StepState.user_id == teacher.user_id)
            )
        ).all()

    assert listed == []
    assert states == []


async def test_a_preview_attempt_is_resumed_until_the_draft_changes(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    previews: FakePreviewRevisions,
    teacher: Actor,
) -> None:
    """LMS-8: the open preview is kept for the same frozen draft only."""
    _, step = await prepared(maker, learning, previews, teacher)
    first = await learning.start_attempt.execute(
        teacher, step.step_id, "quiz", preview=True
    )
    again = await learning.start_attempt.execute(
        teacher, step.step_id, "quiz", preview=True
    )
    previews.revisions[step.step_id] = await add_preview_revision(
        maker, step, content("Quiz (draft 2)", quiz("quiz")), teacher.user_id
    )

    after_edit = await learning.start_attempt.execute(
        teacher, step.step_id, "quiz", preview=True
    )

    assert again.id == first.id
    assert after_edit.id != first.id
    assert [q.id for q in after_edit.questions] == ["q1"]


async def test_previewing_needs_view_drafts(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    previews: FakePreviewRevisions,
    teacher: Actor,
    student: Actor,
    lms_admin: Actor,
) -> None:
    """LMS-5, LMS-8: `view_drafts` (or the LMS admin) opens previews."""
    course, step = await prepared(
        maker, learning, previews, teacher, permissions=("edit",)
    )
    await learning.enroll_in_course.execute(student, course.id)

    with pytest.raises(CoursePermissionError):
        await learning.start_attempt.execute(
            student, step.step_id, "quiz", preview=True
        )
    with pytest.raises(CoursePermissionError):
        await learning.start_attempt.execute(
            teacher, step.step_id, "quiz", preview=True
        )
    allowed = await learning.start_attempt.execute(
        lms_admin, step.step_id, "quiz", preview=True
    )

    assert previews.calls == [(step.step_id, lms_admin.user_id)]
    assert allowed.attempt_no == 1


async def test_preview_attempts_cannot_be_overridden(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    previews: FakePreviewRevisions,
    teacher: Actor,
) -> None:
    """LMS-8: there is nothing to review in a preview."""
    _, step = await prepared(
        maker, learning, previews, teacher, permissions=("view_drafts", "review")
    )
    attempt = await learning.start_attempt.execute(
        teacher, step.step_id, "quiz", preview=True
    )
    await learning.submit_attempt.execute(teacher, attempt.id)

    with pytest.raises(PreviewAttemptError):
        await learning.override_score.execute(teacher, attempt.id, 1.0, "Try.")


async def test_a_wrong_answer_in_a_preview_is_graded_like_a_real_one(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    previews: FakePreviewRevisions,
    teacher: Actor,
) -> None:
    """UF-LMS-09 2: testers check how grading behaves."""
    _, step = await prepared(maker, learning, previews, teacher)
    attempt = await learning.start_attempt.execute(
        teacher, step.step_id, "quiz", preview=True
    )
    await learning.save_answers.execute(teacher, attempt.id, {"q9": {"number": 2}})

    result = await learning.submit_attempt.execute(teacher, attempt.id)

    assert (result.score, result.passed) == (0.0, False)
