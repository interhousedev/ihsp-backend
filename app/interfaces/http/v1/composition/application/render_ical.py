"""Renders lessons as an iCalendar feed (RFC 5545)."""

import datetime as dt
from collections.abc import Mapping, Sequence
from uuid import UUID

from app.shared.contracts.academic import LessonRef
from app.shared.contracts.identity import UserRef

from icalendar import Calendar, Event

PRODID = "-//IHSP//Timetable//EN"
REFRESH = dt.timedelta(hours=1)


def _description(lesson: LessonRef, teachers: Mapping[UUID, UserRef]) -> str:
    """Teacher and topic, one per line."""
    lines: list[str] = []
    teacher = teachers.get(lesson.teacher_id) if lesson.teacher_id else None
    if teacher is not None:
        lines.append(f"{teacher.last_name} {teacher.first_name}")
    if lesson.topic:
        lines.append(lesson.topic)
    return "\n".join(lines)


def _event(
    lesson: LessonRef, teachers: Mapping[UUID, UserRef], now: dt.datetime
) -> Event:
    event = Event()
    event.add("uid", str(lesson.id))
    event.add("dtstamp", now.astimezone(dt.UTC))
    event.add("dtstart", lesson.starts_at.astimezone(dt.UTC))
    event.add("dtend", lesson.ends_at.astimezone(dt.UTC))
    event.add("summary", lesson.subject_name)
    if lesson.room_name:
        event.add("location", lesson.room_name)
    description = _description(lesson, teachers)
    if description:
        event.add("description", description)
    event.add("status", "CANCELLED" if lesson.status == "cancelled" else "CONFIRMED")
    return event


def render_calendar(
    lessons: Sequence[LessonRef],
    teachers: Mapping[UUID, UserRef],
    *,
    name: str,
    now: dt.datetime,
) -> bytes:
    """Return the feed: one VEVENT per lesson with its start and end in UTC."""
    calendar = Calendar()
    calendar.add("prodid", PRODID)
    calendar.add("version", "2.0")
    calendar.add("calscale", "GREGORIAN")
    calendar.add("x-wr-calname", name)
    calendar.add("refresh-interval", REFRESH, parameters={"VALUE": "DURATION"})
    calendar.add("x-published-ttl", "PT1H")
    for lesson in lessons:
        calendar.add_component(_event(lesson, teachers, now))
    return bytes(calendar.to_ical())
