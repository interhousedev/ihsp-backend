"""WEB-23: study order and daily limits as a pure function of the cards."""

from datetime import UTC, datetime, timedelta

from app.modules.flashcards.domain.flashcard import Flashcard
from app.modules.flashcards.domain.study import (
    DailyUsage,
    day_end,
    is_due_today,
    new_today,
    plan_study,
    study_day,
)
from app.shared.ids import new_id
from app.shared.srs import CardState, SrsState

NOW = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)  # 14:00 in Tashkent
SET_ID = new_id()


def make_card(
    position: int,
    state: CardState = CardState.NEW,
    due_in: timedelta | None = None,
) -> Flashcard:
    """A card at `position`; `due_in` is relative to NOW (negative = overdue)."""
    due = None if due_in is None else NOW + due_in
    return Flashcard(
        id=new_id(),
        set_id=SET_ID,
        position=position,
        front=f"front {position}",
        back=f"back {position}",
        srs=SrsState(state=state, due_at=due, interval_days=1.0),
    )


def plan(
    cards: list[Flashcard],
    *,
    new_per_day: int = 20,
    reviews_per_day: int = 200,
    usage: DailyUsage | None = None,
    now: datetime = NOW,
) -> tuple[Flashcard | None, tuple[int, int, int]]:
    """Run plan_study; return the card and (learning, review, new) counts."""
    result = plan_study(
        cards,
        new_per_day=new_per_day,
        reviews_per_day=reviews_per_day,
        usage=usage or DailyUsage(),
        now=now,
    )
    counts = result.counts
    return result.card, (counts.learning, counts.review, counts.new)


def test_due_learning_cards_come_before_reviews_and_new_cards() -> None:
    """WEB-23: order = due learning cards, then reviews, then new cards."""
    new = make_card(0)
    review = make_card(1, CardState.REVIEW, timedelta(hours=-2))
    learning = make_card(2, CardState.LEARNING, timedelta(minutes=-1))

    card, counts = plan([new, review, learning])

    assert card is learning
    assert counts == (1, 1, 1)


def test_reviews_come_before_new_cards_and_the_earliest_due_comes_first() -> None:
    """WEB-23: then reviews due today, the most overdue first."""
    new = make_card(0)
    later = make_card(1, CardState.REVIEW, timedelta(hours=-1))
    earlier = make_card(2, CardState.REVIEW, timedelta(days=-3))

    card, _ = plan([new, later, earlier])

    assert card is earlier


def test_new_cards_come_in_list_order() -> None:
    """WEB-24: the position decides which new card is introduced first."""
    second = make_card(1)
    first = make_card(0)

    card, counts = plan([second, first])

    assert card is first
    assert counts == (0, 0, 2)


def test_a_learning_card_that_is_not_due_yet_waits_but_is_counted() -> None:
    """WEB-23: a card due in 10 minutes is not offered now; new cards are."""
    waiting = make_card(0, CardState.LEARNING, timedelta(minutes=10))
    new = make_card(1)

    card, counts = plan([waiting, new])

    assert card is new
    assert counts == (1, 0, 1)


def test_reviews_due_after_today_are_not_offered() -> None:
    """WEB-23: a review due tomorrow (Tashkent day) stays out of today's queue."""
    tomorrow = make_card(0, CardState.REVIEW, day_end(NOW) - NOW)
    today = make_card(1, CardState.REVIEW, day_end(NOW) - NOW - timedelta(seconds=1))

    card, counts = plan([tomorrow, today])

    assert card is today
    assert counts == (0, 1, 0)


def test_nothing_is_offered_when_nothing_is_due() -> None:
    """UF-WEB-22: the session ends with a summary when nothing is due."""
    far = make_card(0, CardState.REVIEW, timedelta(days=4))

    card, counts = plan([far])

    assert card is None
    assert counts == (0, 0, 0)


def test_the_21st_new_card_is_not_offered_with_20_new_per_day() -> None:
    """WEB-23: daily limit of new cards (default 20)."""
    cards = [make_card(i) for i in range(25)]

    last_allowed, counts = plan(cards, usage=DailyUsage(new=19))
    blocked, blocked_counts = plan(cards, usage=DailyUsage(new=20))

    assert last_allowed is cards[0]
    assert counts == (0, 0, 1)
    assert blocked is None
    assert blocked_counts == (0, 0, 0)


def test_the_review_limit_hides_the_remaining_reviews_but_not_new_cards() -> None:
    """WEB-23: daily limit of reviews (default 200); new cards still follow."""
    reviews = [make_card(i, CardState.REVIEW, timedelta(hours=-1)) for i in range(3)]
    new = make_card(3)

    in_limit, counts = plan([*reviews, new], reviews_per_day=2, usage=DailyUsage())
    over, over_counts = plan(
        [*reviews, new], reviews_per_day=2, usage=DailyUsage(review=2)
    )

    assert in_limit is reviews[0]
    assert counts == (0, 2, 1)
    assert over is new
    assert over_counts == (0, 0, 1)


def test_learning_cards_ignore_both_daily_limits() -> None:
    """WEB-23: learning and relearning cards are never limited."""
    learning = make_card(0, CardState.RELEARNING, timedelta(minutes=-5))

    card, counts = plan(
        [learning],
        new_per_day=1,
        reviews_per_day=1,
        usage=DailyUsage(new=1, review=1),
    )

    assert card is learning
    assert counts == (1, 0, 0)


def test_the_study_day_is_the_tashkent_day() -> None:
    """The day rolls over at 00:00 in Tashkent (19:00 UTC), not at midnight UTC."""
    before = datetime(2026, 10, 6, 18, 59, tzinfo=UTC)
    after = datetime(2026, 10, 6, 19, 0, tzinfo=UTC)

    assert study_day(before).isoformat() == "2026-10-06"
    assert study_day(after).isoformat() == "2026-10-07"
    assert day_end(before) == after


def test_due_today_counts_seen_cards_due_before_the_day_ends() -> None:
    """WEB-22: `due_today` = not new and due before the end of today."""
    end = day_end(NOW)
    due = make_card(0, CardState.REVIEW, timedelta(hours=-1))
    later = make_card(1, CardState.REVIEW, end - NOW)

    assert is_due_today(due, end)
    assert not is_due_today(later, end)
    assert not is_due_today(make_card(2), end)


def test_new_today_is_what_is_left_of_the_daily_limit() -> None:
    """WEB-22: min(new cards, new_per_day - introduced today), never negative."""
    assert new_today(5, 20, 0) == 5
    assert new_today(50, 20, 15) == 5
    assert new_today(50, 20, 25) == 0
