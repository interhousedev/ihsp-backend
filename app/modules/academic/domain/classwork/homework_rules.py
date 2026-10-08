"""Pure homework rules: text checks, to-do buckets, the "updated" badge."""

import datetime as dt
from typing import Literal

from app.modules.academic.domain.classwork.errors import (
    HomeworkNoteTooLongError,
    HomeworkTextError,
    TopicTooLongError,
)

HOMEWORK_TEXT_MAX = 4000
NOTE_MAX = 1000
TOPIC_MAX = 300
DONE_RETENTION_DAYS = 60

Bucket = Literal["upcoming", "later", "done", "overdue"]


def clean_homework_text(value: str) -> str:
    """Trim the text; it must be 1..4000 characters."""
    text = value.strip()
    if not text or len(text) > HOMEWORK_TEXT_MAX:
        raise HomeworkTextError(params={"max": HOMEWORK_TEXT_MAX})
    return text


def clean_topic(value: str | None) -> str | None:
    """Trim the topic; empty clears it (ACA-21)."""
    text = (value or "").strip()
    if len(text) > TOPIC_MAX:
        raise TopicTooLongError(params={"max": TOPIC_MAX})
    return text or None


def clean_note(value: str | None) -> str | None:
    """Trim a private note; empty clears it, more than 1000 characters fails."""
    text = (value or "").strip()
    if len(text) > NOTE_MAX:
        raise HomeworkNoteTooLongError(params={"max": NOTE_MAX})
    return text or None


def bucket(
    done_at: dt.datetime | None,
    due_date: dt.date | None,
    today: dt.date,
    next_study_day: dt.date | None,
) -> Bucket:
    """Sort an item into the to-do lists (ACA-10, WEB-18).

    Done items go to ``done``. Open items due from today up to the next study
    day are ``upcoming``; later or undated ones are ``later``; items whose due
    date has passed are ``overdue`` and are not shown.
    """
    if done_at is not None:
        return "done"
    if due_date is None:
        return "later"
    if due_date < today:
        return "overdue"
    if due_date <= (next_study_day or today):
        return "upcoming"
    return "later"


def is_updated(
    homework_updated_at: dt.datetime | None, todo_updated_at: dt.datetime | None
) -> bool:
    """True if the teacher edited the homework after the student last touched it."""
    if homework_updated_at is None:
        return False
    if todo_updated_at is None:
        return True
    return homework_updated_at > todo_updated_at
