"""Rules for the text and numbers a student can put into a set."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.flashcards.domain.errors import InvalidCardsError, InvalidSetError
from app.modules.flashcards.domain.limits import (
    CARD_TEXT_MAX,
    CARD_TEXT_MIN,
    DESCRIPTION_MAX,
    MAX_CARDS_PER_SET,
    NEW_PER_DAY_MAX,
    NEW_PER_DAY_MIN,
    REVIEWS_PER_DAY_MAX,
    REVIEWS_PER_DAY_MIN,
    TITLE_MAX,
    TITLE_MIN,
)


def _cards_error(reason: str) -> InvalidCardsError:
    return InvalidCardsError(
        params={
            "reason": reason,
            "max_cards": MAX_CARDS_PER_SET,
            "max_chars": CARD_TEXT_MAX,
        }
    )


def _set_error(field: str, low: int, high: int) -> InvalidSetError:
    return InvalidSetError(params={"field": field, "min": low, "max": high})


def check_card_count(count: int) -> None:
    """Raise unless a set would hold at most 500 cards."""
    if count > MAX_CARDS_PER_SET:
        raise _cards_error("count")


def check_unique_ids(card_ids: Sequence[UUID]) -> None:
    """Raise if a card id appears twice in one list."""
    if len(card_ids) != len(set(card_ids)):
        raise _cards_error("duplicate-id")


def check_card_text(front: str, back: str) -> None:
    """Raise unless both sides have 1 to 2000 characters."""
    for side in (front, back):
        if not CARD_TEXT_MIN <= len(side) <= CARD_TEXT_MAX:
            raise _cards_error("text")


def clean_title(title: str) -> str:
    """Return the trimmed title; raise unless it has 1 to 200 characters."""
    cleaned = " ".join(title.split())
    if not TITLE_MIN <= len(cleaned) <= TITLE_MAX:
        raise _set_error("title", TITLE_MIN, TITLE_MAX)
    return cleaned


def clean_description(description: str | None) -> str | None:
    """Return the trimmed description, None when blank; raise if over 1000 chars."""
    if description is None:
        return None
    cleaned = description.strip()
    if len(cleaned) > DESCRIPTION_MAX:
        raise _set_error("description", 0, DESCRIPTION_MAX)
    return cleaned or None


def check_new_per_day(value: int) -> int:
    """Return the daily new-card limit; raise unless it is 1 to 200."""
    if not NEW_PER_DAY_MIN <= value <= NEW_PER_DAY_MAX:
        raise _set_error("new_per_day", NEW_PER_DAY_MIN, NEW_PER_DAY_MAX)
    return value


def check_reviews_per_day(value: int) -> int:
    """Return the daily review limit; raise unless it is 1 to 2000."""
    if not REVIEWS_PER_DAY_MIN <= value <= REVIEWS_PER_DAY_MAX:
        raise _set_error("reviews_per_day", REVIEWS_PER_DAY_MIN, REVIEWS_PER_DAY_MAX)
    return value
