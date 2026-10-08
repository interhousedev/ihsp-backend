"""BOT-13: how settings buttons turn into preference patches."""

from uuid import uuid4

from app.interfaces.bot.settings_patch import (
    SCREEN_OF_KEY,
    preference_patch,
    subject_patch,
)
from app.shared.contracts.identity import UserPreferences

import pytest


@pytest.mark.parametrize(
    ("key", "value", "expected"),
    [
        ("lang", "uz", {"locale": "uz"}),
        ("lang", "de", None),
        ("marks_enabled", "0", {"marks_enabled": False}),
        ("drops", "1", {"alerts_drops": True}),
        ("gpa_below", "4.0", {"alerts_gpa_below": 4.0}),
        ("gpa_below", "off", {"alerts_gpa_below": None}),
        ("gpa_below", "9", None),
        ("sem_below", "3.5", {"alerts_semester_mark_below": 3.5}),
        ("mark_below", "4", {"alerts_mark_below": 4}),
        ("mark_below", "7", None),
        ("lead", "10", {"lessons_links_lead_min": 10}),
        ("lead", "7", None),
        ("prompt", "0", {"lessons_prompt_enabled": False}),
        ("unknown", "1", None),
    ],
)
def test_setting_values(
    key: str, value: str, expected: dict[str, object] | None
) -> None:
    """Valid presses give a patch, invalid ones nothing."""
    assert preference_patch(UserPreferences(), key, value) == expected


def test_mark_type_is_toggled_and_keeps_canonical_order() -> None:
    """Turning midterm off, then on again, keeps lesson, midterm, final order."""
    prefs = UserPreferences()

    off = preference_patch(prefs, "type", "midterm")
    assert off == {"marks_types": ["lesson", "final"]}

    again = UserPreferences(marks_types=["lesson", "final"])
    assert preference_patch(again, "type", "midterm") == {
        "marks_types": ["lesson", "midterm", "final"]
    }


def test_mark_value_is_toggled() -> None:
    """Values 2..5 are toggles."""
    patch = preference_patch(UserPreferences(), "value", "2")

    assert patch == {"marks_values": [3, 4, 5]}


def test_every_key_has_a_screen_to_show_after_the_change() -> None:
    """After a press the bot re-renders the screen the key belongs to."""
    assert set(SCREEN_OF_KEY) >= {"lang", "type", "gpa_below", "lead", "prompt"}


def test_deselecting_one_subject_stores_the_others_as_strings() -> None:
    """No stored filter means all subjects; one toggle stores the rest."""
    ids = [uuid4(), uuid4(), uuid4()]

    patch = subject_patch(UserPreferences(), ids, 1)

    assert patch == {"marks_subject_ids": [str(ids[0]), str(ids[2])]}


def test_selecting_every_subject_again_clears_the_filter() -> None:
    """All subjects selected is stored as None."""
    ids = [uuid4(), uuid4()]
    prefs = UserPreferences(marks_subject_ids=[ids[0]])

    assert subject_patch(prefs, ids, 1) == {"marks_subject_ids": None}


def test_subject_position_out_of_range_is_ignored() -> None:
    """A stale button must not crash."""
    assert subject_patch(UserPreferences(), [uuid4()], 5) is None
