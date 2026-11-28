"""The learner's own record over the real database: attempts, reviews, verdicts."""

from typing import Any, cast

from app.modules.lms.application.learning.ai_review import AiReviews
from app.modules.lms.domain.learning.ai_review_errors import (
    AiReviewSessionNotFoundError,
)
from app.modules.lms.domain.learning.errors import (
    AttemptNotFoundError,
    CourseNotFoundError,
)
from app.modules.lms.infrastructure.learning.ai_review_store import SqlAiReviewStore
from app.modules.lms.ports.learning.ai_review_store import NewAiReviewMessage
from app.modules.lms.wiring_learning import LearningServices
from app.shared.actor import Actor
from tests.lms.learning.builders import content, quiz, seed_course
from tests.lms.learning.integration.test_exam_blocks import _exam
from tests.lms.learning.scenarios import ONE_RIGHT, RIGHT, quiz_course, take

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def test_other_users_attempt_not_found(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
    other_student: Actor,
) -> None:
    """Another student's attempt id looks exactly like a missing one."""
    course, step = await quiz_course(maker, learning, student)
    await learning.enroll_in_course.execute(other_student, course.id)
    mine = await take(learning, student, step, RIGHT)

    own = await learning.learning_record.my_attempt(student, mine.id)
    assert own.attempt_id == mine.id
    with pytest.raises(AttemptNotFoundError):
        await learning.learning_record.my_attempt(other_student, mine.id)
    page = await learning.learning_record.my_attempts(other_student, course.id)
    assert page.attempts == []


async def test_review_hidden_when_show_answers_off(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """`show_answers: never` keeps prompts, explanations and answers out."""
    _, step = await quiz_course(maker, learning, student, show_answers="never")
    result = await take(learning, student, step, ONE_RIGHT)

    view = await learning.learning_record.my_attempt(student, result.id)

    assert view.review_shown is False
    assert [q.correct for q in view.questions] == [True, False, False]
    for question in view.questions:
        assert question.prompt is None
        assert question.explanation is None
        assert question.correct_answer is None


async def test_open_exam_never_listed(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """An exam sitting in progress and an unsubmitted test are not attempts yet."""
    course = await seed_course(
        maker,
        steps=[("s", content("SAT", _exam())), ("q", content("Quiz", quiz("quiz")))],
    )
    await learning.enroll_in_course.execute(student, course.id)
    await learning.exam_start.execute(student, course.step("s").step_id, "sat")
    await learning.start_attempt.execute(
        student, course.step("q").step_id, "quiz", preview=False
    )

    page = await learning.learning_record.my_attempts(student, course.id)

    assert page.attempts == []
    assert page.next_cursor is None


async def test_not_enrolled_course_not_found(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
    other_student: Actor,
) -> None:
    """A course the caller is not enrolled in does not exist for them."""
    course, _ = await quiz_course(maker, learning, student)

    with pytest.raises(CourseNotFoundError):
        await learning.learning_record.my_attempts(other_student, course.id)
    with pytest.raises(CourseNotFoundError):
        await learning.learning_record.course_progress(other_student, course.id)
    assert await learning.learning_record.courses(other_student) == []
    assert [c.course_id for c in await learning.learning_record.courses(student)] == [
        course.id
    ]


async def test_ai_review_returns_verdict_only(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
    other_student: Actor,
) -> None:
    """The verdict carries the last review, never the chat; only for the owner."""
    course, step = await quiz_course(maker, learning, student)
    store = SqlAiReviewStore(maker)
    reviews = AiReviews(
        uow_factory=cast(Any, None),
        gate=cast(Any, None),
        store=store,
        files=cast(Any, None),
        identity=cast(Any, None),
        source_reader=cast(Any, None),
        model=None,
        web=None,
        limits=cast(Any, None),
        rate_limiter=cast(Any, None),
        completion=cast(Any, None),
    )
    session = await store.create_session(
        course_id=course.id,
        step_id=step.step_id,
        block_id="essay",
        user_id=student.user_id,
    )

    empty = await reviews.verdict_of(student, session.id)
    assert (empty.reviewed, empty.summary, empty.scores) == (False, None, [])

    await store.append(
        session.id,
        [
            NewAiReviewMessage(
                role="student",
                kind="chat",
                text="My private draft",
                openui=None,
                history="My private draft",
            ),
            NewAiReviewMessage(
                role="assistant",
                kind="review",
                text="Good structure",
                openui=None,
                history="Good structure",
            ),
        ],
        status="reviewed",
    )

    verdict = await reviews.verdict_of(student, session.id)

    assert verdict.session_id == session.id
    assert (verdict.status, verdict.reviewed) == ("reviewed", True)
    assert verdict.summary == "Good structure"
    assert "My private draft" not in verdict.model_dump_json()
    assert set(verdict.model_dump()) == {
        "session_id",
        "status",
        "reviewed",
        "summary",
        "scores",
        "strengths",
        "improvements",
        "total",
        "max_total",
    }
    with pytest.raises(AiReviewSessionNotFoundError):
        await reviews.verdict_of(other_student, session.id)
