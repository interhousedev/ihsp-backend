"""Building the room page model from lessons and their resources (ROOM-4)."""

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from uuid import UUID

from app.modules.links.application.link_urls import LinkUrls
from app.modules.links.application.room_day import (
    PreviousDay,
    RoomAuthorLine,
    RoomDay,
    RoomItem,
    RoomLessonBlock,
)
from app.modules.links.application.views import ResourceView
from app.modules.links.domain.link import LessonRole
from app.shared.clock import to_local
from app.shared.contracts.academic import LessonRef, RoomRef
from app.shared.contracts.identity import UserRef

WEEKDAYS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)
PREVIOUS_DAYS = 7
SUNDAY = 6
PIN_PLACEHOLDER = "__PIN__"


def strip_scheme(url: str) -> str:
    """Drop `http://` or `https://` from a URL."""
    return url.split("://", 1)[-1]


def teacher_name(user: UserRef | None) -> str:
    """Return 'Kalandarova G.' for a teacher."""
    if user is None:
        return ""
    initial = f" {user.first_name[:1]}." if user.first_name else ""
    return f"{user.last_name}{initial}"


class RoomDayBuilder:
    """Turns lessons, resources and teachers into a RoomDay."""

    def __init__(self, urls: LinkUrls, rooms_url: str) -> None:
        """Store the URL builder and the base URL of room pages."""
        self.urls = urls
        self.rooms_url = rooms_url.rstrip("/")

    def build(
        self,
        room: RoomRef,
        day: date,
        *,
        today: date,
        now: datetime,
        lessons: Sequence[LessonRef],
        resources: Mapping[UUID, Sequence[ResourceView]],
        teachers: Mapping[UUID, UserRef],
    ) -> RoomDay:
        """Build the day: the heading, lesson blocks and previous day links."""
        label = f"{WEEKDAYS[day.weekday()]} {day:%d.%m}"
        heading = f"{strip_scheme(self.rooms_url)}/{room.slug} · {label}"
        ordered = sorted(lessons, key=lambda item: (item.period, item.starts_at))
        blocks = tuple(
            self._block(
                lesson,
                resources.get(lesson.id, ()),
                teachers,
                now if day == today else None,
            )
            for lesson in ordered
        )
        empty = None if blocks else self._empty(room, day, today)
        return RoomDay(
            heading=heading,
            empty_text=empty,
            lessons=blocks,
            previous=self._previous(room, day),
            today_href=None if day == today else self._href(room, None),
            day=day,
        )

    def _empty(self, room: RoomRef, day: date, today: date) -> str:
        when = "today" if day == today else f"on {day:%d.%m}"
        return f"No lessons in room {room.name} {when}"

    def _href(self, room: RoomRef, day: date | None) -> str:
        base = f"{self.rooms_url}/{room.slug}?pin={PIN_PLACEHOLDER}"
        return base if day is None else f"{base}&date={day.isoformat()}"

    def _previous(self, room: RoomRef, day: date) -> tuple[PreviousDay, ...]:
        found: list[PreviousDay] = []
        cursor = day
        while len(found) < PREVIOUS_DAYS:
            cursor -= timedelta(days=1)
            if cursor.weekday() != SUNDAY:
                found.append(PreviousDay(f"{cursor:%d.%m}", self._href(room, cursor)))
        return tuple(found)

    def _block(
        self,
        lesson: LessonRef,
        resources: Sequence[ResourceView],
        teachers: Mapping[UUID, UserRef],
        now: datetime | None,
    ) -> RoomLessonBlock:
        current = (
            now is not None
            and lesson.status == "scheduled"
            and lesson.starts_at <= now < lesson.ends_at
        )
        start = to_local(lesson.starts_at)
        end = to_local(lesson.ends_at)
        teacher = (
            teacher_name(teachers.get(lesson.teacher_id)) if lesson.teacher_id else ""
        )
        parts = [lesson.subject_name, ", ".join(lesson.group_names), teacher]
        materials = [r for r in resources if r.link.lesson_role is LessonRole.MATERIAL]
        attachments = [
            r for r in resources if r.link.lesson_role is LessonRole.ATTACHMENT
        ]
        return RoomLessonBlock(
            prefix="[now] " if current else "      ",
            period=lesson.period,
            time=f"{start:%H:%M}–{end:%H:%M}",
            summary=" · ".join(part for part in parts if part),
            cancelled=lesson.status == "cancelled",
            materials=tuple(self._item(r) for r in materials),
            authors=self._authors(attachments),
        )

    def _authors(
        self, attachments: Sequence[ResourceView]
    ) -> tuple[RoomAuthorLine, ...]:
        grouped: dict[str, list[RoomItem]] = {}
        for view in attachments:
            name = view.author.first_name or "?"
            grouped.setdefault(name, []).append(self._item(view))
        width = max((len(name) for name in grouped), default=0)
        return tuple(
            RoomAuthorLine(name=name.ljust(width), items=tuple(items))
            for name, items in grouped.items()
        )

    def _item(self, view: ResourceView) -> RoomItem:
        return RoomItem(
            href=view.short_url,
            text=strip_scheme(view.short_url),
            title=view.title,
            report_href=self.urls.report_url(view.link.slug),
        )
