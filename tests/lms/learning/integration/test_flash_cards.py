"""LMS-14, LMS-18, WEB-23, UF-LMS-03: studying the flash cards of a block."""

from app.modules.lms.domain.learning.errors import (
    BlockNotFoundError,
    CardNotFoundError,
    NotEnrolledError,
)
from app.modules.lms.domain.step_content import Card, FlashcardsBlock
from app.modules.lms.wiring_learning import LearningServices
from app.shared.actor import Actor
from app.shared.srs import Rating
from tests.fakes.clock import FixedClock
from tests.lms.learning.builders import (
    SeededCourse,
    cards,
    content,
    publish_version,
    seed_course,
)

import pytest
from fakeredis.aioredis import FakeRedis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def card_course(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor | None,
    count: int = 3,
) -> SeededCourse:
    """A course with one step that holds a flash card block `cards`."""
    course = await seed_course(
        maker, steps=[("s1", content("Cards", cards(count=count)))]
    )
    if student is not None:
        await learning.enroll_in_course.execute(student, course.id)
    return course


async def test_the_first_card_is_a_new_one_with_the_button_intervals(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """WEB-23: each button shows when the card comes back."""
    course = await card_course(maker, learning, student)

    view = await learning.next_card.execute(student, course.step("s1").step_id, "cards")

    assert view.block_id == "cards"
    assert (view.card.id, view.card.front, view.card.back) == (
        "c1",
        "Front 1",
        "Back 1",
    )
    assert view.intervals.model_dump() == {
        "again": "1m",
        "hard": "1m",
        "medium": "10m",
        "easy": "4d",
    }
    assert view.counts.model_dump() == {"learning": 0, "review": 0, "new": 3}


async def test_rating_a_card_reschedules_it_and_offers_the_next_one(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
    clock: FixedClock,
) -> None:
    """LMS-18: Anki-like rating; the card waits for its learning step."""
    course = await card_course(maker, learning, student)
    step_id = course.step("s1").step_id

    after = await learning.review_card.execute(student, step_id, "c1", Rating.MEDIUM)
    clock.advance(minutes=11)
    later = await learning.next_card.execute(student, step_id, "cards")

    assert after.card.id == "c2"
    assert after.counts.model_dump() == {"learning": 0, "review": 0, "new": 2}
    assert later.card.id == "c1"
    assert later.counts.learning == 1
    assert later.intervals.medium == "1d"
    assert later.intervals.easy == "4d"


async def test_reviews_are_counted_in_redis_for_the_day_with_a_48_hour_expiry(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
    redis: FakeRedis,
) -> None:
    """LMS-18: daily limits use `fc:day:{user}:{block}:{date}`."""
    course = await card_course(maker, learning, student)
    step_id = course.step("s1").step_id

    await learning.review_card.execute(student, step_id, "c1", Rating.AGAIN)
    await learning.review_card.execute(student, step_id, "c2", Rating.EASY)

    key = f"fc:day:{student.user_id}:cards:2026-10-06"
    assert await redis.hget(key, "new") == "2"
    assert await redis.hget(key, "review") is None
    assert 0 < await redis.ttl(key) <= 48 * 3600


async def test_the_twenty_first_new_card_of_a_day_is_not_offered(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
    clock: FixedClock,
) -> None:
    """WEB-23: daily limit of 20 new cards."""
    course = await card_course(maker, learning, student, count=25)
    step_id = course.step("s1").step_id
    view = await learning.next_card.execute(student, step_id, "cards")
    for _ in range(20):
        view = await learning.review_card.execute(
            student, step_id, view.card.id, Rating.AGAIN
        )

    assert view.card is None
    assert view.counts.new == 0
    clock.advance(minutes=2)
    later = await learning.next_card.execute(student, step_id, "cards")
    assert later.counts.learning == 20
    assert later.counts.new == 0
    tomorrow_cards = await learning.get_step_view.execute(student, course.id, step_id)
    assert tomorrow_cards.blocks[0].due == 20


async def test_a_new_day_brings_new_cards_again(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
    clock: FixedClock,
) -> None:
    """WEB-23: the daily counters are per local day."""
    course = await card_course(maker, learning, student, count=25)
    step_id = course.step("s1").step_id
    view = await learning.next_card.execute(student, step_id, "cards")
    for _ in range(20):
        view = await learning.review_card.execute(
            student, step_id, view.card.id, Rating.EASY
        )

    clock.advance(hours=24)
    next_day = await learning.next_card.execute(student, step_id, "cards")

    assert next_day.counts.new == 5


async def test_card_progress_survives_a_new_version_for_cards_that_still_exist(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
    clock: FixedClock,
) -> None:
    """LMS-14: flash card progress stays for cards that still exist."""
    course = await card_course(maker, learning, student)
    step_id = course.step("s1").step_id
    await learning.review_card.execute(student, step_id, "c1", Rating.MEDIUM)
    await learning.review_card.execute(student, step_id, "c2", Rating.EASY)

    kept = FlashcardsBlock(
        id="cards",
        cards=[
            Card(id="c1", front="New front", back="Back 1"),
            Card(id="c3", front="Front 3", back="Back 3"),
            Card(id="c4", front="Front 4", back="Back 4"),
        ],
    )
    await publish_version(maker, course, [("s1", content("Cards", kept))])
    clock.advance(minutes=11)
    view = await learning.next_card.execute(student, step_id, "cards")

    assert view.card.id == "c1"
    assert view.card.front == "New front"
    assert view.counts.model_dump() == {"learning": 1, "review": 0, "new": 2}
    with pytest.raises(CardNotFoundError):
        await learning.review_card.execute(student, step_id, "c2", Rating.EASY)


async def test_cards_are_for_enrolled_students_of_known_blocks_and_cards(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
    other_student: Actor,
) -> None:
    """LMS-18: access and unknown ids."""
    course = await card_course(maker, learning, student)
    step_id = course.step("s1").step_id

    with pytest.raises(NotEnrolledError):
        await learning.next_card.execute(other_student, step_id, "cards")
    with pytest.raises(NotEnrolledError):
        await learning.review_card.execute(other_student, step_id, "c1", Rating.EASY)
    with pytest.raises(BlockNotFoundError):
        await learning.next_card.execute(student, step_id, "nope")
    with pytest.raises(CardNotFoundError):
        await learning.review_card.execute(student, step_id, "nope", Rating.EASY)


async def test_students_progress_in_cards_is_separate(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
    other_student: Actor,
) -> None:
    """LMS-18: progress is per student."""
    course = await card_course(maker, learning, student)
    await learning.enroll_in_course.execute(other_student, course.id)
    step_id = course.step("s1").step_id

    await learning.review_card.execute(student, step_id, "c1", Rating.EASY)
    mine = await learning.next_card.execute(student, step_id, "cards")
    theirs = await learning.next_card.execute(other_student, step_id, "cards")

    assert (mine.card.id, mine.counts.new) == ("c2", 2)
    assert (theirs.card.id, theirs.counts.new) == ("c1", 3)
