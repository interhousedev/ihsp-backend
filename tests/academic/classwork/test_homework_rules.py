"""ACA-10, WEB-18..20: homework lists, notes and the "updated" badge."""

import datetime as dt

from app.modules.academic.domain.classwork.errors import (
    HomeworkNoteTooLongError,
    HomeworkTextError,
    TopicTooLongError,
)
from app.modules.academic.domain.classwork.homework_rules import (
    bucket,
    clean_homework_text,
    clean_note,
    clean_topic,
    is_updated,
)

import pytest

FRIDAY = dt.date(2026, 10, 9)
SATURDAY = dt.date(2026, 10, 10)
MONDAY = dt.date(2026, 10, 12)
THURSDAY = dt.date(2026, 10, 8)
NOON = dt.datetime(2026, 10, 9, 7, 0, tzinfo=dt.UTC)


@pytest.mark.parametrize(
    ("done_at", "due", "expected"),
    [
        (None, SATURDAY, "upcoming"),
        (None, FRIDAY, "upcoming"),
        (None, MONDAY, "later"),
        (None, None, "later"),
        (None, THURSDAY, "overdue"),
        (NOON, SATURDAY, "done"),
        (NOON, None, "done"),
    ],
)
def test_friday_with_a_saturday_study_day_sorts_items_into_lists(
    done_at: dt.datetime | None, due: dt.date | None, expected: str
) -> None:
    """WEB-18: Upcoming is due next study day, Later is the rest, Done is ticked."""
    assert bucket(done_at, due, FRIDAY, SATURDAY) == expected


def test_without_a_next_study_day_only_today_is_upcoming() -> None:
    """The lists still work in the last days of the term."""
    assert bucket(None, FRIDAY, FRIDAY, None) == "upcoming"
    assert bucket(None, SATURDAY, FRIDAY, None) == "later"


def test_edit_after_the_student_touched_the_item_shows_updated() -> None:
    """UF-WEB-13 1b: the badge shows until the student ticks or notes again."""
    edited = dt.datetime(2026, 10, 7, 10, 0, tzinfo=dt.UTC)
    touched = dt.datetime(2026, 10, 7, 9, 0, tzinfo=dt.UTC)

    assert is_updated(edited, touched)
    assert not is_updated(touched, edited)
    assert is_updated(edited, None)
    assert not is_updated(None, touched)


def test_homework_text_is_trimmed_and_must_not_be_empty() -> None:
    """ACA-10: homework is text."""
    assert clean_homework_text("  Read page 5 ") == "Read page 5"
    with pytest.raises(HomeworkTextError):
        clean_homework_text("   ")
    with pytest.raises(HomeworkTextError):
        clean_homework_text("x" * 4001)


def test_note_is_limited_to_1000_characters_and_empty_clears_it() -> None:
    """WEB-20: up to 1000 characters."""
    assert clean_note("x" * 1000) == "x" * 1000
    assert clean_note("  ") is None
    assert clean_note(None) is None
    with pytest.raises(HomeworkNoteTooLongError):
        clean_note("x" * 1001)


def test_topic_is_limited_and_empty_clears_it() -> None:
    """ACA-21: the topic is short text."""
    assert clean_topic(" Waves ") == "Waves"
    assert clean_topic("") is None
    with pytest.raises(TopicTooLongError):
        clean_topic("x" * 301)
