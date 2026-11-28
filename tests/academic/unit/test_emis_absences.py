"""New EMIS absences: what counts as news and the notices they produce."""

import datetime as dt
from uuid import uuid4

from app.modules.academic.domain.marks.emis_absences import (
    emis_absence_drafts,
    new_absent_dates,
)
from app.shared.contracts.identity import UserPreferences
from app.shared.notifications import NotificationType

TODAY = dt.date(2026, 10, 6)
DAY_1 = TODAY - dt.timedelta(days=1)
OLD = TODAY - dt.timedelta(days=3)


def test_only_unseen_recent_dates_are_new() -> None:
    """Known dates, old dates and future dates are not news."""
    current = [TODAY, DAY_1, OLD, TODAY + dt.timedelta(days=1)]
    assert new_absent_dates([DAY_1], current, today=TODAY) == [TODAY]
    assert new_absent_dates(None, current, today=TODAY) == [DAY_1, TODAY]


def test_no_flags_or_turned_present_gives_nothing() -> None:
    """An absence corrected to present drops out and is never announced."""
    assert new_absent_dates([TODAY], None, today=TODAY) == []
    assert new_absent_dates([TODAY], [], today=TODAY) == []


def test_drafts_carry_subject_date_and_dedupe_key() -> None:
    """One lesson_absence draft per date, deduped per student, subject and date."""
    user_id, subject_id = uuid4(), uuid4()
    (draft,) = emis_absence_drafts(
        user_id=user_id,
        prefs=UserPreferences(locale="en"),
        subject_id=subject_id,
        subject_name={"uz": "Matematika", "ru": "Математика", "en": "Mathematics"},
        dates=[TODAY],
    )
    assert draft.type == NotificationType.LESSON_ABSENCE
    assert draft.payload["source"] == "emis"
    assert draft.payload["subject_name"] == "Mathematics"
    assert draft.payload["date"] == TODAY.isoformat()
    assert draft.dedupe_key == f"emis_absence:{user_id}:{subject_id}:{TODAY}"


def test_preference_off_sends_nothing() -> None:
    """notify_absences=False silences the notices."""
    drafts = emis_absence_drafts(
        user_id=uuid4(),
        prefs=UserPreferences(notify_absences=False),
        subject_id=uuid4(),
        subject_name={"ru": "Физика"},
        dates=[TODAY],
    )
    assert drafts == []
