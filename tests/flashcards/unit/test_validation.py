"""WEB-22-24: limits of titles, card texts, card counts and daily limits."""

from app.modules.flashcards.domain.errors import InvalidCardsError, InvalidSetError
from app.modules.flashcards.domain.limits import CARD_TEXT_MAX, MAX_CARDS_PER_SET
from app.modules.flashcards.domain.validation import (
    check_card_count,
    check_card_text,
    check_new_per_day,
    check_reviews_per_day,
    check_unique_ids,
    clean_description,
    clean_title,
)
from app.shared.ids import new_id

import pytest


def test_a_set_may_hold_exactly_500_cards() -> None:
    """Plan B10: cards <= 500."""
    check_card_count(MAX_CARDS_PER_SET)

    with pytest.raises(InvalidCardsError) as raised:
        check_card_count(MAX_CARDS_PER_SET + 1)

    assert raised.value.params["reason"] == "count"
    assert raised.value.params["max_cards"] == 500


@pytest.mark.parametrize("length", [1, 2000])
def test_card_sides_of_1_to_2000_characters_are_accepted(length: int) -> None:
    """Plan B10: front and back are 1-2000 characters."""
    check_card_text("a" * length, "b" * length)


@pytest.mark.parametrize(
    ("front", "back"),
    [
        ("", "back"),
        ("front", ""),
        ("a" * (CARD_TEXT_MAX + 1), "back"),
        ("front", "b" * (CARD_TEXT_MAX + 1)),
    ],
)
def test_empty_or_oversized_card_sides_are_rejected(front: str, back: str) -> None:
    """Plan B10: an empty or 2001-character side breaks the rule."""
    with pytest.raises(InvalidCardsError) as raised:
        check_card_text(front, back)

    assert raised.value.params == {
        "reason": "text",
        "max_cards": 500,
        "max_chars": 2000,
    }


def test_the_same_card_id_twice_is_rejected() -> None:
    """WEB-24: one card cannot appear twice in a saved list."""
    one = new_id()

    check_unique_ids([one, new_id()])
    with pytest.raises(InvalidCardsError) as raised:
        check_unique_ids([one, one])

    assert raised.value.params["reason"] == "duplicate-id"


def test_a_title_is_trimmed_and_limited_to_200_characters() -> None:
    """WEB-22: titles have 1 to 200 characters after trimming."""
    assert clean_title("  Cell   biology \n") == "Cell biology"
    assert len(clean_title("t" * 200)) == 200
    for bad in ("", "   ", "t" * 201):
        with pytest.raises(InvalidSetError) as raised:
            clean_title(bad)
        assert raised.value.params["field"] == "title"


def test_a_blank_description_means_no_description() -> None:
    """WEB-22: descriptions are optional and at most 1000 characters."""
    assert clean_description(None) is None
    assert clean_description("  \n") is None
    assert clean_description(" Mitosis ") == "Mitosis"
    with pytest.raises(InvalidSetError):
        clean_description("d" * 1001)


@pytest.mark.parametrize("value", [1, 20, 200])
def test_new_per_day_accepts_1_to_200(value: int) -> None:
    """WEB-23: daily new-card limit 1-200."""
    assert check_new_per_day(value) == value


@pytest.mark.parametrize("value", [0, 201, -5])
def test_new_per_day_rejects_values_out_of_range(value: int) -> None:
    """WEB-23: 0 and 201 are refused, not clamped."""
    with pytest.raises(InvalidSetError) as raised:
        check_new_per_day(value)

    assert raised.value.params == {"field": "new_per_day", "min": 1, "max": 200}


@pytest.mark.parametrize("value", [1, 200, 2000])
def test_reviews_per_day_accepts_1_to_2000(value: int) -> None:
    """WEB-23: daily review limit 1-2000."""
    assert check_reviews_per_day(value) == value


@pytest.mark.parametrize("value", [0, 2001])
def test_reviews_per_day_rejects_values_out_of_range(value: int) -> None:
    """WEB-23: 0 and 2001 are refused."""
    with pytest.raises(InvalidSetError) as raised:
        check_reviews_per_day(value)

    assert raised.value.params["max"] == 2000


def test_errors_are_validation_errors_with_stable_codes() -> None:
    """Problem+json: 422 with `flashcards/...` types."""
    cards, fields = InvalidCardsError(), InvalidSetError()

    assert (cards.status, cards.code) == (422, "flashcards/invalid-cards")
    assert (fields.status, fields.code) == (422, "flashcards/invalid-set")
