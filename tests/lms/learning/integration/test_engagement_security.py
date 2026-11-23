"""Engagement over the real database: answer policy, access and XP farming."""

from decimal import Decimal

from app.modules.lms.application.engagement.service import EngagementService
from app.modules.lms.domain.access_rules import AccessRule, Audience
from app.modules.lms.domain.engagement.errors import ReviewItemNotFoundError
from app.modules.lms.domain.engagement.xp import (
    DAILY_TEST_XP_LIMIT,
    TEST_SCORE_XP,
    attempt_xp,
)
from app.modules.lms.infrastructure.access_rule_repository import (
    SqlAccessRuleRepository,
)
from app.modules.lms.infrastructure.orm.enrollment import Enrollment
from app.modules.lms.wiring_engagement import build_engagement
from app.modules.lms.wiring_learning import LearningServices
from app.shared.actor import Actor
from app.shared.wiring import ModuleDeps
from tests.fakes.clock import FixedClock
from tests.lms.learning.builders import SeededCourse, content, quiz, seed_course
from tests.lms.learning.fakes.identity import FakeIdentityDirectory
from tests.lms.learning.scenarios import (
    ONE_RIGHT,
    QUESTIONS,
    RIGHT,
    WRONG,
    quiz_course,
    take,
)

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.fixture
def engagement(deps: ModuleDeps, identity: FakeIdentityDirectory) -> EngagementService:
    """The engagement service as wired in production."""
    return build_engagement(deps, identity=identity)


async def _questions(engagement: EngagementService, student: Actor) -> list[str]:
    queue = await engagement.review_queue(student)
    return [i.item_id for i in queue.items if i.kind == "question"]


async def _test_xp(engagement: EngagementService, student: Actor) -> list[int]:
    history = await engagement.xp_history(student, 100)
    return [i.xp for i in history.items if i.source == "test"]


async def test_hidden_answers_are_never_queued(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    engagement: EngagementService,
    student: Actor,
    clock: FixedClock,
) -> None:
    """`show_answers: never` keeps missed questions out of the review queue."""
    _, step = await quiz_course(maker, learning, student, show_answers="never")
    await take(learning, student, step, WRONG)
    clock.advance(minutes=1)

    assert await _questions(engagement, student) == []


async def test_last_attempt_policy_queues_only_after_the_last_attempt(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    engagement: EngagementService,
    student: Actor,
    clock: FixedClock,
) -> None:
    """While attempts remain the key stays hidden; after the last one it shows."""
    _, step = await quiz_course(
        maker, learning, student, show_answers="after_last_attempt", max_attempts=2
    )
    await take(learning, student, step, WRONG)
    clock.advance(minutes=1)
    assert await _questions(engagement, student) == []

    await take(learning, student, step, WRONG)
    clock.advance(minutes=1)
    items = await _questions(engagement, student)
    assert len(items) == 3
    result = await engagement.answer(student, items[0], RIGHT["q1"])
    assert result.correct_answer is not None


async def test_answer_requires_a_due_item(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    engagement: EngagementService,
    student: Actor,
    clock: FixedClock,
) -> None:
    """An item that is not due cannot be answered again for its key."""
    _, step = await quiz_course(maker, learning, student)
    await take(learning, student, step, WRONG)
    clock.advance(minutes=1)
    item = (await _questions(engagement, student))[0]

    first = await engagement.answer(student, item, {})
    assert first.next_due > clock.now()
    with pytest.raises(ReviewItemNotFoundError):
        await engagement.answer(student, item, {})


async def test_unenrolled_learner_loses_review_items(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    engagement: EngagementService,
    student: Actor,
    clock: FixedClock,
) -> None:
    """After leaving the course its items vanish and answering them is a 404."""
    _, step = await quiz_course(maker, learning, student)
    await take(learning, student, step, WRONG)
    clock.advance(minutes=1)
    item = (await _questions(engagement, student))[0]
    async with maker() as session:
        await session.execute(
            delete(Enrollment).where(Enrollment.user_id == student.user_id)
        )
        await session.commit()

    assert await _questions(engagement, student) == []
    assert (await engagement.summary(student)).review_due == 0
    with pytest.raises(ReviewItemNotFoundError):
        await engagement.answer(student, item, RIGHT["q1"])


async def test_step_closed_by_audience_hides_its_items(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    engagement: EngagementService,
    student: Actor,
    clock: FixedClock,
) -> None:
    """A lesson rule that now excludes the learner hides its review items."""
    course, step = await quiz_course(maker, learning, student)
    await take(learning, student, step, WRONG)
    clock.advance(minutes=1)
    item = (await _questions(engagement, student))[0]
    async with maker() as session:
        await SqlAccessRuleRepository(session).save(
            course.id, step.step_id, AccessRule(Audience.CHOSEN), course.created_by
        )
        await session.commit()

    assert await _questions(engagement, student) == []
    with pytest.raises(ReviewItemNotFoundError):
        await engagement.answer(student, item, RIGHT["q1"])


async def test_retakes_earn_xp_only_for_a_new_best(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    engagement: EngagementService,
    student: Actor,
    clock: FixedClock,
) -> None:
    """Repeating a test earns nothing; improving earns only the score gain."""
    _, step = await quiz_course(maker, learning, student)
    await take(learning, student, step, WRONG)
    clock.advance(minutes=1)
    await take(learning, student, step, WRONG)
    clock.advance(minutes=1)
    await take(learning, student, step, ONE_RIGHT)
    clock.advance(minutes=1)
    await take(learning, student, step, ONE_RIGHT)
    clock.advance(minutes=1)

    one = Decimal(1)
    first = attempt_xp(None, one)
    gains = await _test_xp(engagement, student)
    assert sorted(gains) == sorted([first, attempt_xp(one, Decimal(3)) - first])
    assert sum(gains) <= attempt_xp(one, one) == first + TEST_SCORE_XP


async def test_test_xp_has_a_daily_cap(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    engagement: EngagementService,
    student: Actor,
    clock: FixedClock,
) -> None:
    """Many perfect tests in one day stop earning at the daily cap."""
    keys = [f"quiz{i}" for i in range(5)]
    course: SeededCourse = await seed_course(
        maker, steps=[(k, content(k, quiz("quiz", QUESTIONS))) for k in keys]
    )
    await learning.enroll_in_course.execute(student, course.id)
    for key in keys:
        await take(learning, student, course.step(key), RIGHT)
        clock.advance(seconds=1)

    assert 5 * attempt_xp(Decimal(1), Decimal(1)) > DAILY_TEST_XP_LIMIT
    assert sum(await _test_xp(engagement, student)) == DAILY_TEST_XP_LIMIT
