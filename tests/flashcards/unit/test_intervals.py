"""WEB-23: the button labels ("1m", "10m", "1d", "4d", "2mo") of the study screen."""

from datetime import UTC, datetime, timedelta

from app.modules.flashcards.domain.intervals import format_interval
from app.shared.srs import Rating, SrsState, preview

import pytest

NOW = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("delta", "label"),
    [
        (timedelta(seconds=10), "1m"),
        (timedelta(minutes=1), "1m"),
        (timedelta(minutes=10), "10m"),
        (timedelta(minutes=59, seconds=59), "59m"),
        (timedelta(hours=1), "1h"),
        (timedelta(hours=23), "23h"),
        (timedelta(days=1), "1d"),
        (timedelta(days=4), "4d"),
        (timedelta(days=2.9), "2d"),
        (timedelta(days=29), "29d"),
        (timedelta(days=30), "1mo"),
        (timedelta(days=60), "2mo"),
        (timedelta(days=400), "13mo"),
    ],
)
def test_interval_labels(delta: timedelta, label: str) -> None:
    """WEB-23: minutes under an hour, then hours, days and months (rounded down)."""
    assert format_interval(delta) == label


def test_a_new_card_shows_1m_1m_10m_4d() -> None:
    """WEB-23: Again 1m, Hard 1m, Medium 10m, Easy 4d for a new card."""
    labels = {r: format_interval(d) for r, d in preview(SrsState(), NOW).items()}

    assert labels == {
        Rating.AGAIN: "1m",
        Rating.HARD: "1m",
        Rating.MEDIUM: "10m",
        Rating.EASY: "4d",
    }
