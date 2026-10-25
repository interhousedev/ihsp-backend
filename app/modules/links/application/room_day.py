"""The data of one room page: lessons, resource lines and previous days."""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class RoomItem:
    """One link on a room page with its title and report link."""

    href: str
    text: str
    title: str
    report_href: str


@dataclass(frozen=True, slots=True)
class RoomAuthorLine:
    """Attachments of one author: '{first name} - {link} ({title}), ...'."""

    name: str
    items: tuple[RoomItem, ...]


@dataclass(frozen=True, slots=True)
class RoomLessonBlock:
    """One lesson of the day with its materials and attachments."""

    prefix: str
    period: int
    time: str
    summary: str
    cancelled: bool
    materials: tuple[RoomItem, ...]
    authors: tuple[RoomAuthorLine, ...]


@dataclass(frozen=True, slots=True)
class PreviousDay:
    """A link to an earlier day of the same room."""

    label: str
    href: str


@dataclass(frozen=True, slots=True)
class RoomDay:
    """Everything the room template needs."""

    heading: str
    empty_text: str | None
    lessons: tuple[RoomLessonBlock, ...]
    previous: tuple[PreviousDay, ...]
    today_href: str | None
    day: date
