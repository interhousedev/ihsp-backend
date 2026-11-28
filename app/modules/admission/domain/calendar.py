"""RFC 5545 rendering of the deadline calendar and the feed token. Pure."""

import datetime as dt
import hashlib
import secrets
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

TASHKENT: Final = ZoneInfo("Asia/Tashkent")
DEFAULT_ALARM_OFFSETS: Final = (7, 1)
MAX_ALARMS: Final = 5
MAX_OFFSET_DAYS: Final = 90
EXAMS: Final = ("ielts", "toefl", "duolingo", "sat", "act")
_LINE: Final = 75

CalendarSourceName = Literal[
    "university",
    "checklist",
    "exam",
    "opportunity",
    "test_score",
    "personal",
    "milestone",
]


@dataclass(frozen=True, slots=True)
class CalendarEntry:
    """One dated item of a student's calendar.

    `key` is stable across runs and unique per student (it makes the ICS UID
    and the reminder dedupe key). `day` is the local (Tashkent) date shown;
    `due_utc` is the instant reminders count back from (the end of `day` when
    only a date is known). `url_path` is a path inside the admission app.
    `remind` False leaves the entry out of the reminder job (another job sends
    it). Titles are already localised; only titles and dates reach the feed.
    `title_key` and `subject` let a notification re-localise the title for its
    reader (`<text of title_key> · <subject>`); `title` is the fallback.
    """

    key: str
    source: CalendarSourceName
    title: str
    day: dt.date
    due_utc: dt.datetime
    all_day: bool = True
    url_path: str | None = None
    predicted: bool = False
    remind: bool = True
    title_key: str | None = None
    subject: str | None = None
    list_entry_id: UUID | None = None
    description: str | None = None


@dataclass(frozen=True, slots=True)
class CalendarFeed:
    """A private ICS subscription; only the SHA-256 of the token is kept."""

    id: UUID
    user_id: UUID
    token_hash: str
    locale: str
    alarm_offsets: tuple[int, ...] | None
    created_at: dt.datetime
    revoked_at: dt.datetime | None = None


@dataclass(frozen=True, slots=True)
class ExamDate:
    """A test date with its registration deadline, kept by staff."""

    id: UUID
    exam: str
    test_date: dt.date
    registration_deadline: dt.date
    source_url: str | None = None


def new_token() -> str:
    """A 256-bit URL-safe token, shown to the user once."""
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    """The SHA-256 hex digest kept at rest."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def clean_offsets(offsets: Iterable[int]) -> tuple[int, ...]:
    """Distinct offsets in days within 0..90, largest first, at most five."""
    kept = sorted({int(o) for o in offsets if 0 <= int(o) <= MAX_OFFSET_DAYS})
    return tuple(reversed(kept))[:MAX_ALARMS]


def end_of_day(day: dt.date) -> dt.datetime:
    """23:59 Tashkent of the date, in UTC: the instant of a date-only deadline."""
    return dt.datetime.combine(day, dt.time(23, 59), TASHKENT).astimezone(dt.UTC)


def _escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def _fold(line: str) -> str:
    """Fold at 75 octets without splitting a UTF-8 sequence."""
    out: list[str] = []
    current = b""
    limit = _LINE
    for ch in line:
        enc = ch.encode("utf-8")
        if len(current) + len(enc) > limit:
            out.append(current.decode("utf-8"))
            current = b""
            limit = _LINE - 1
        current += enc
    out.append(current.decode("utf-8"))
    return "\r\n ".join(out)


def _stamp(at: dt.datetime) -> str:
    return at.astimezone(dt.UTC).strftime("%Y%m%dT%H%M%SZ")


def entry_uid(user_key: str, entry_key: str) -> str:
    """A stable UID that reveals neither the user nor the entry."""
    digest = hashlib.sha256(f"{user_key}:{entry_key}".encode()).hexdigest()[:32]
    return f"{digest}@admission"


def render_ics(
    entries: Sequence[CalendarEntry],
    *,
    calendar_name: str,
    user_key: str,
    alarm_offsets: Sequence[int],
    now: dt.datetime,
) -> str:
    """A VCALENDAR with one VEVENT per entry: titles and dates only."""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//IHSP//Admission calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape(calendar_name)}",
        "X-WR-TIMEZONE:Asia/Tashkent",
        "REFRESH-INTERVAL;VALUE=DURATION:PT6H",
        "X-PUBLISHED-TTL:PT6H",
    ]
    stamp = _stamp(now)
    for e in entries:
        lines += [
            "BEGIN:VEVENT",
            f"UID:{entry_uid(user_key, e.key)}",
            f"DTSTAMP:{stamp}",
        ]
        if e.all_day:
            nxt = e.day + dt.timedelta(days=1)
            lines += [
                f"DTSTART;VALUE=DATE:{e.day:%Y%m%d}",
                f"DTEND;VALUE=DATE:{nxt:%Y%m%d}",
                "TRANSP:TRANSPARENT",
            ]
        else:
            lines += [
                f"DTSTART:{_stamp(e.due_utc)}",
                f"DTEND:{_stamp(e.due_utc)}",
            ]
        lines.append(f"SUMMARY:{_escape(e.title)}")
        if e.description:
            lines.append(f"DESCRIPTION:{_escape(e.description)}")
        for days in alarm_offsets:
            lines += [
                "BEGIN:VALARM",
                "ACTION:DISPLAY",
                f"DESCRIPTION:{_escape(e.title)}",
                f"TRIGGER:-P{days}D" if days else "TRIGGER:PT0S",
                "END:VALARM",
            ]
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "".join(_fold(line) + "\r\n" for line in lines)
