"""LMS-15 to LMS-17, UF-LMS-04: starting, saving, submitting and grading attempts."""

from datetime import datetime
from decimal import Decimal

from app.modules.lms.domain.learning.entities import Attempt
from app.modules.lms.domain.learning.errors import (
    AnswerInvalidError,
    AttemptClosedError,
    AttemptCooldownError,
    AttemptNotFoundError,
    AttemptNumberTakenError,
    AttemptStartConflictError,
    BlockNotFoundError,
    NoAttemptsLeftError,
    NotEnrolledError,
)
from app.modules.lms.domain.learning.variant import Variant
from app.modules.lms.infrastructure.learning.repositories.attempt_repository import (
    SqlAttemptRepository,
)
from app.modules.lms.infrastructure.learning.uow import SqlLearningUnitOfWork
from app.modules.lms.wiring_learning import LearningServices
from app.shared.actor import Actor
from app.shared.db.uow_testing import noop_audit_writer, noop_outbox_writer
from app.shared.ids import new_id
from tests.fakes.clock import FixedClock
from tests.lms.learning.builders import (
    choice,
    content,
    number_question,
    publish_version,
    quiz,
    seed_course,
    text_question,
)
from tests.lms.learning.helpers import FORBIDDEN_KEYS, keys_of
from tests.lms.learning.scenarios import (
    ONE_RIGHT,
    RIGHT,
    WRONG,
    quiz_course,
    take,
)

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def test_starting_an_attempt_returns_questions_without_correct_answers(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """LMS-17, UF-LMS-04 2: the browser gets questions, never answers."""
    _, step = await quiz_course(maker, learning, student)

    attempt = await learning.start_attempt.execute(
        student, step.step_id, "quiz", preview=False
    )

    body = attempt.model_dump(mode="json")
    assert attempt.attempt_no == 1
    assert attempt.block_id == "quiz"
    assert attempt.deadline_at is None
    assert attempt.submitted_at is None
    assert attempt.answers == {}
    assert [q["id"] for q in body["questions"]] == ["q1", "q2", "q3"]
    assert body["questions"][0]["options"] == [
        {"id": "q1-a", "text": "Option a"},
        {"id": "q1-b", "text": "Option b"},
        {"id": "q1-c", "text": "Option c"},
    ]
    assert not FORBIDDEN_KEYS & keys_of(body)


async def test_reloading_the_page_resumes_the_same_attempt_with_its_answers(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """UF-LMS-04 3a, LMS-17: the same variant and the saved answers."""
    _, step = await quiz_course(
        maker, learning, student, shuffle_questions=True, shuffle_options=True
    )
    first = await learning.start_attempt.execute(
        student, step.step_id, "quiz", preview=False
    )
    await learning.save_answers.execute(student, first.id, {"q2": {"number": 4}})

    again = await learning.start_attempt.execute(
        student, step.step_id, "quiz", preview=False
    )

    assert again.id == first.id
    assert again.attempt_no == 1
    assert [q.id for q in again.questions] == [q.id for q in first.questions]
    assert again.questions == first.questions
    assert again.answers == {"q2": {"number": 4}}


async def test_a_pool_attempt_has_only_the_pool_size_of_questions(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """LMS-16: N of M questions per attempt."""
    _, step = await quiz_course(maker, learning, student, pool_size=2)

    first = await learning.start_attempt.execute(
        student, step.step_id, "quiz", preview=False
    )
    await learning.submit_attempt.execute(student, first.id)
    second = await learning.start_attempt.execute(
        student, step.step_id, "quiz", preview=False
    )

    assert len(first.questions) == len(second.questions) == 2
    assert second.attempt_no == 2


async def test_a_block_that_is_not_a_test_is_not_found(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """LMS-2: attempts are for test blocks."""
    _, step = await quiz_course(maker, learning, student)

    with pytest.raises(BlockNotFoundError):
        await learning.start_attempt.execute(
            student, step.step_id, "nope", preview=False
        )


async def test_only_enrolled_students_can_start_attempts(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    other_student: Actor,
    student: Actor,
) -> None:
    """LMS-19: enrollment is required (staff preview is a separate path)."""
    _, step = await quiz_course(maker, learning, student)

    with pytest.raises(NotEnrolledError):
        await learning.start_attempt.execute(
            other_student, step.step_id, "quiz", preview=False
        )


async def test_the_attempts_limit_is_enforced_and_shown(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """LMS-16, UF-LMS-04 2a: no attempts left -> Start is refused."""
    course, step = await quiz_course(maker, learning, student, max_attempts=2)
    await take(learning, student, step, WRONG)
    await take(learning, student, step, WRONG)

    with pytest.raises(NoAttemptsLeftError):
        await learning.start_attempt.execute(
            student, step.step_id, "quiz", preview=False
        )
    view = await learning.get_step_view.execute(student, course.id, step.step_id)

    assert view.blocks[0].rules.attempts_left == 0
    assert view.blocks[0].open_attempt_id is None


async def test_the_pause_between_attempts_is_enforced(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
    clock: FixedClock,
) -> None:
    """LMS-16, UF-LMS-04 2b: 'Next attempt available at 16:20'."""
    _, step = await quiz_course(maker, learning, student, cooldown_sec=300)
    await take(learning, student, step, WRONG)
    available = clock.now().replace(minute=5)

    with pytest.raises(AttemptCooldownError) as caught:
        await learning.start_attempt.execute(
            student, step.step_id, "quiz", preview=False
        )
    clock.advance(minutes=5, seconds=1)
    second = await learning.start_attempt.execute(
        student, step.step_id, "quiz", preview=False
    )

    assert datetime.fromisoformat(caught.value.params["available_at"]) == available
    assert second.attempt_no == 2


async def test_a_time_limited_attempt_is_submitted_by_the_next_read_after_the_deadline(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
    clock: FixedClock,
) -> None:
    """LMS-16, UF-LMS-04 4: time runs out -> auto-submit with the saved answers."""
    course, step = await quiz_course(maker, learning, student, time_limit_sec=600)
    started = clock.now()
    attempt = await learning.start_attempt.execute(
        student, step.step_id, "quiz", preview=False
    )
    await learning.save_answers.execute(
        student, attempt.id, {"q1": {"option_ids": ["q1-a"]}}
    )
    clock.advance(minutes=11)

    view = await learning.get_step_view.execute(student, course.id, step.step_id)
    result = await learning.get_attempt.execute(student, attempt.id)

    assert attempt.deadline_at is not None
    assert (attempt.deadline_at - started).total_seconds() == 600
    assert view.blocks[0].open_attempt_id is None
    assert view.blocks[0].best is not None
    assert view.blocks[0].best.score == 1.0
    assert result.submitted_at == attempt.deadline_at
    assert (result.score, result.max_score, result.passed) == (1.0, 3.0, False)


async def test_answers_after_the_deadline_are_refused_and_the_attempt_is_submitted(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
    clock: FixedClock,
) -> None:
    """LMS-16: late answers are not accepted; what was saved is graded."""
    _, step = await quiz_course(maker, learning, student, time_limit_sec=60)
    attempt = await learning.start_attempt.execute(
        student, step.step_id, "quiz", preview=False
    )
    await learning.save_answers.execute(student, attempt.id, {"q2": {"number": 4}})
    clock.advance(seconds=61)

    with pytest.raises(AttemptClosedError):
        await learning.save_answers.execute(student, attempt.id, RIGHT)
    result = await learning.get_attempt.execute(student, attempt.id)

    assert result.score == 1.0
    assert result.answers == {"q2": {"number": 4}}


async def test_an_expired_attempt_is_closed_before_a_new_one_starts(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
    clock: FixedClock,
) -> None:
    """LMS-16: an open attempt is returned only while it has time left."""
    _, step = await quiz_course(maker, learning, student, time_limit_sec=60)
    first = await learning.start_attempt.execute(
        student, step.step_id, "quiz", preview=False
    )
    clock.advance(seconds=120)

    second = await learning.start_attempt.execute(
        student, step.step_id, "quiz", preview=False
    )

    assert second.id != first.id
    assert second.attempt_no == 2


async def test_submitting_grades_on_the_server_and_twice_gives_the_same_result(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """LMS-15, LMS-17: all-or-nothing per question, score = sum of points."""
    _, step = await quiz_course(maker, learning, student)
    attempt = await learning.start_attempt.execute(
        student, step.step_id, "quiz", preview=False
    )
    await learning.save_answers.execute(student, attempt.id, ONE_RIGHT)

    first = await learning.submit_attempt.execute(student, attempt.id)
    again = await learning.submit_attempt.execute(student, attempt.id)

    assert (first.score, first.max_score, first.passed) == (1.0, 3.0, False)
    assert again == first


async def test_saved_answers_are_merged_per_question(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """UF-LMS-04 3: answers are saved as the student goes."""
    _, step = await quiz_course(maker, learning, student)
    attempt = await learning.start_attempt.execute(
        student, step.step_id, "quiz", preview=False
    )

    await learning.save_answers.execute(
        student, attempt.id, {"q1": {"option_ids": ["q1-b"]}}
    )
    saved = await learning.save_answers.execute(
        student, attempt.id, {"q1": {"option_ids": ["q1-a"]}, "q3": {"text": "yes"}}
    )

    assert saved.answers == {"q1": {"option_ids": ["q1-a"]}, "q3": {"text": "yes"}}


async def test_invalid_answers_are_refused(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """LMS-17: answers must fit the questions of the attempt."""
    _, step = await quiz_course(maker, learning, student)
    attempt = await learning.start_attempt.execute(
        student, step.step_id, "quiz", preview=False
    )

    with pytest.raises(AnswerInvalidError):
        await learning.save_answers.execute(
            student, attempt.id, {"q1": {"option_ids": ["not-an-option"]}}
        )


async def test_a_submitted_attempt_accepts_no_more_answers(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """UF-LMS-04: the result is final."""
    _, step = await quiz_course(maker, learning, student)
    attempt = await learning.start_attempt.execute(
        student, step.step_id, "quiz", preview=False
    )
    await learning.submit_attempt.execute(student, attempt.id)

    with pytest.raises(AttemptClosedError):
        await learning.save_answers.execute(student, attempt.id, RIGHT)


async def test_attempts_belong_to_their_owner(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
    other_student: Actor,
) -> None:
    """LMS-17: nobody else can save to, submit or read an attempt."""
    _, step = await quiz_course(maker, learning, student)
    attempt = await learning.start_attempt.execute(
        student, step.step_id, "quiz", preview=False
    )

    with pytest.raises(AttemptNotFoundError):
        await learning.save_answers.execute(other_student, attempt.id, RIGHT)
    with pytest.raises(AttemptNotFoundError):
        await learning.submit_attempt.execute(other_student, attempt.id)
    with pytest.raises(AttemptNotFoundError):
        await learning.get_attempt.execute(other_student, attempt.id)


@pytest.mark.parametrize(
    ("policy", "max_attempts", "answers", "shown"),
    [
        ("never", None, RIGHT, False),
        ("after_submit", None, WRONG, True),
        ("after_pass", None, RIGHT, True),
        ("after_pass", None, WRONG, False),
        ("after_last_attempt", 2, WRONG, False),
        ("after_last_attempt", 1, WRONG, True),
    ],
)
async def test_correct_answers_are_shown_only_as_show_answers_allows(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
    policy: str,
    max_attempts: int | None,
    answers: dict,
    shown: bool,
) -> None:
    """LMS-16, LMS-17: never / after submit / after pass / after the last attempt."""
    _, step = await quiz_course(
        maker, learning, student, show_answers=policy, max_attempts=max_attempts
    )

    result = await take(learning, student, step, answers)

    assert (result.review is not None) is shown
    if shown:
        assert [item.question_id for item in result.review] == ["q1", "q2", "q3"]
        assert result.review[0].correct_answer == {"option_ids": ["q1-a"]}
        assert result.review[0].explanation == "Because."


async def test_passing_completes_the_step_and_updates_the_course_progress(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """LMS-19: all tests passed -> the step is completed and progress follows."""
    course, step = await quiz_course(
        maker, learning, student, with_text_step=True, passing_score_pct=60
    )

    failed = await take(learning, student, step, WRONG)
    after_fail = await learning.get_step_view.execute(student, course.id, step.step_id)
    passed = await take(learning, student, step, RIGHT)
    after_pass = await learning.get_step_view.execute(student, course.id, step.step_id)
    mine = await learning.list_my_courses.execute(student)

    assert failed.passed is False and passed.passed is True
    assert after_fail.completed is False
    assert after_pass.completed is True
    assert mine.enrolled[0].progress_pct == 50


async def test_a_step_with_two_tests_needs_both_passed(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """LMS-19: 'a step is completed when all its tests are passed'."""
    body = content(
        "Two tests",
        quiz("first", [choice("a1", correct=["a"])]),
        quiz("second", [number_question("b1", value=1)]),
    )
    course = await seed_course(maker, steps=[("s1", body)])
    await learning.enroll_in_course.execute(student, course.id)
    step = course.step("s1")

    await take(
        learning, student, step, {"a1": {"option_ids": ["a1-a"]}}, block_id="first"
    )
    midway = await learning.get_step_view.execute(student, course.id, step.step_id)
    await take(learning, student, step, {"b1": {"number": 1}}, block_id="second")
    done = await learning.get_step_view.execute(student, course.id, step.step_id)

    assert midway.completed is False
    assert done.completed is True


async def test_the_best_attempt_counts_toward_the_result(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """UF-LMS-04: the best result counts toward completion."""
    course, step = await quiz_course(maker, learning, student)
    await take(learning, student, step, RIGHT)
    await take(learning, student, step, WRONG)

    view = await learning.get_step_view.execute(student, course.id, step.step_id)

    assert view.blocks[0].best.score == 3.0
    assert view.completed is True


async def test_an_attempt_continues_on_its_revision_after_a_new_version_is_published(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """UF-LMS-04 3b, LMS-14: grading uses the revision the attempt started with."""
    course, step = await quiz_course(maker, learning, student)
    attempt = await learning.start_attempt.execute(
        student, step.step_id, "quiz", preview=False
    )
    await learning.save_answers.execute(student, attempt.id, RIGHT)
    changed = [
        choice("q1", correct=["b"]),
        number_question("q2", value=9),
        text_question("q3", accepted=["maybe"]),
    ]

    await publish_version(
        maker, course, [("quiz", content("Quiz", quiz("quiz", changed)))]
    )
    result = await learning.submit_attempt.execute(student, attempt.id)
    review = await learning.get_attempt.execute(student, attempt.id)

    assert (result.score, result.passed) == (3.0, True)
    assert review.revision_id == step.revision_id
    new_view = await learning.get_step_view.execute(student, course.id, step.step_id)
    assert new_view.revision_id != step.revision_id
    assert new_view.blocks[0].best.score == 3.0


async def test_a_new_attempt_after_a_new_version_uses_the_new_revision(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """LMS-14: new attempts start on the live revision."""
    course, step = await quiz_course(maker, learning, student)
    await take(learning, student, step, RIGHT)
    await publish_version(
        maker,
        course,
        [("quiz", content("Quiz", quiz("quiz", [choice("q1", correct=["b"])])))],
    )

    second = await take(
        learning, student, course.step("quiz"), {"q1": {"option_ids": ["q1-a"]}}
    )

    assert second.passed is False
    assert second.max_score == 1.0


# - - - Races and uniqueness - - -


def an_attempt(course_step: object, number: int) -> Attempt:
    """An attempt entity for the repository tests."""
    return Attempt(
        id=new_id(),
        user_id=USER,
        step_id=course_step.step_id,  # type: ignore[attr-defined]
        revision_id=course_step.revision_id,  # type: ignore[attr-defined]
        block_id="quiz",
        attempt_no=number,
        is_preview=False,
        variant=Variant(("q1",), {}),
        started_at=datetime.fromisoformat("2026-10-06T09:00:00+00:00"),
        deadline_at=None,
        max_score=Decimal(1),
    )


USER = new_id()


async def test_the_repository_refuses_a_second_attempt_with_the_same_number(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """UF-LMS-04: a double Start can't exceed the attempts limit."""
    _, step = await quiz_course(maker, learning, None)

    async with SqlLearningUnitOfWork(
        maker, noop_outbox_writer, noop_audit_writer
    ) as uow:
        await uow.attempts.add(an_attempt(step, 1))
        with pytest.raises(AttemptNumberTakenError):
            await uow.attempts.add(an_attempt(step, 1))


async def test_preview_attempts_may_share_a_number_without_conflict(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
) -> None:
    """LMS-8: the unique index only covers real attempts."""
    _, step = await quiz_course(maker, learning, None)
    first, second = an_attempt(step, 1), an_attempt(step, 1)
    first.is_preview = second.is_preview = True

    async with SqlLearningUnitOfWork(
        maker, noop_outbox_writer, noop_audit_writer
    ) as uow:
        await uow.attempts.add(first)
        await uow.attempts.add(second)
        await uow.commit()


async def test_a_lost_race_on_the_attempt_number_is_retried_once(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """UF-LMS-04: the loser of a double click retries and ends with an attempt."""
    _, step = await quiz_course(maker, learning, student)
    original = SqlAttemptRepository.add
    calls: list[int] = []

    async def flaky(self: SqlAttemptRepository, attempt: Attempt) -> None:
        calls.append(attempt.attempt_no)
        if len(calls) == 1:
            raise AttemptNumberTakenError()
        await original(self, attempt)

    monkeypatch.setattr(SqlAttemptRepository, "add", flaky)

    started = await learning.start_attempt.execute(
        student, step.step_id, "quiz", preview=False
    )

    assert len(calls) == 2
    assert started.attempt_no == 1


async def test_a_second_lost_race_is_a_conflict_error(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """UF-LMS-04: after one retry the conflict is reported."""
    _, step = await quiz_course(maker, learning, student)

    async def always(self: SqlAttemptRepository, attempt: Attempt) -> None:
        raise AttemptNumberTakenError()

    monkeypatch.setattr(SqlAttemptRepository, "add", always)

    with pytest.raises(AttemptStartConflictError):
        await learning.start_attempt.execute(
            student, step.step_id, "quiz", preview=False
        )
