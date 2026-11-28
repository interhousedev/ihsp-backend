"""Student notices about absences EMIS reported for the first time."""

import datetime as dt
from collections.abc import Collection, Mapping
from uuid import UUID

from app.shared.contracts.identity import UserPreferences
from app.shared.notifications import NotificationDraft, NotificationType

# EMIS absences older than this many days are history, not news: no notice.
NOTICE_MAX_AGE_DAYS = 2


def new_absent_dates(
    previous: Collection[dt.date] | None,
    current: Collection[dt.date] | None,
    *,
    today: dt.date,
) -> list[dt.date]:
    """Dates absent now, not stored before, and at most two days old.

    A date that turned from absent to present simply drops out of ``current``; it
    never produces a notice, and the dedupe key stops a second notice if EMIS flips
    it back.
    """
    if not current:
        return []
    known = set(previous or ())
    oldest = today - dt.timedelta(days=NOTICE_MAX_AGE_DAYS)
    return sorted(d for d in set(current) - known if oldest <= d <= today)


def emis_absence_drafts(
    *,
    user_id: UUID,
    prefs: UserPreferences,
    subject_id: UUID,
    subject_name: Mapping[str, str],
    dates: Collection[dt.date],
) -> list[NotificationDraft]:
    """One ``lesson_absence`` notice per new EMIS absence (subject and date)."""
    if not prefs.notify_absences:
        return []
    name = subject_name.get(prefs.locale) or next(iter(subject_name.values()), "")
    return [
        NotificationDraft(
            user_id=user_id,
            type=NotificationType.LESSON_ABSENCE,
            payload={
                "source": "emis",
                "date": day.isoformat(),
                "subject_name": name,
                "update": False,
            },
            dedupe_key=f"emis_absence:{user_id}:{subject_id}:{day.isoformat()}",
        )
        for day in sorted(dates)
    ]
