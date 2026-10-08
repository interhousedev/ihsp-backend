"""Open a room page: PIN form, wrong PIN, cached or fresh day (ROOM-1..ROOM-8)."""

import secrets
from datetime import date, timedelta
from uuid import UUID

from app.modules.links.application.not_found_counter import NotFoundCounter
from app.modules.links.application.public_pages import PublicPages
from app.modules.links.application.resource_builder import ResourceBuilder
from app.modules.links.application.room_day_builder import (
    PIN_PLACEHOLDER,
    RoomDayBuilder,
)
from app.modules.links.application.views import ResourceView, WebResponse
from app.modules.links.domain.locale import pick_locale
from app.modules.links.ports.page_renderer import PageRenderer
from app.modules.links.ports.pin_limiter import PinLimiter
from app.modules.links.ports.room_page_cache import RoomPageCache
from app.modules.links.ports.unit_of_work import UowFactory
from app.shared.base_error import RateLimitedError
from app.shared.clock import Clock, local_today
from app.shared.contracts.academic import RoomRef, ScheduleQueries
from app.shared.contracts.identity import IdentityDirectory

MAX_DAYS_BACK = 31
MAX_SLUG_LENGTH = 100


def parse_day(raw: str | None, today: date) -> date:
    """Return the requested day, clamped to the last 31 days up to today."""
    if raw:
        try:
            requested = date.fromisoformat(raw)
        except ValueError:
            return today
        return max(today - timedelta(days=MAX_DAYS_BACK), min(requested, today))
    return today


class RenderRoomPage:
    """Answers `GET /r/{room_slug}?pin=&date=`."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        schedule: ScheduleQueries,
        identity: IdentityDirectory,
        builder: ResourceBuilder,
        day_builder: RoomDayBuilder,
        renderer: PageRenderer,
        cache: RoomPageCache,
        pin_limiter: PinLimiter,
        not_found: NotFoundCounter,
        pages: PublicPages,
        clock: Clock,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.schedule = schedule
        self.identity = identity
        self.builder = builder
        self.day_builder = day_builder
        self.renderer = renderer
        self.cache = cache
        self.pin_limiter = pin_limiter
        self.not_found = not_found
        self.pages = pages
        self.clock = clock

    async def execute(
        self,
        slug: str,
        *,
        pin: str | None,
        day: str | None,
        ip: str | None,
        accept_language: str | None,
    ) -> WebResponse:
        """Return the HTTP answer for the room page request."""
        locale = pick_locale(accept_language)
        try:
            return await self._answer(slug, pin, day, ip, locale)
        except RateLimitedError as error:
            return self.pages.rate_limited(locale, error.params.get("retry_after"))

    async def _answer(
        self,
        slug: str,
        pin: str | None,
        raw_day: str | None,
        ip: str | None,
        locale: str,
    ) -> WebResponse:
        room = await self._room(slug, ip)
        if room is None:
            return self.pages.not_found(locale)
        wait = await self.pin_limiter.retry_after(slug, ip)
        if wait is not None:
            return self.pages.rate_limited(locale, wait)
        if not pin:
            return self._form(room, raw_day, locale, wrong=False, status=200)
        if not secrets.compare_digest(pin.encode(), room.pin.encode()):
            await self.pin_limiter.record_failure(slug, ip)
            return self._form(room, raw_day, locale, wrong=True, status=403)
        today = local_today(self.clock)
        html = await self._day_html(room, parse_day(raw_day, today), today)
        return WebResponse(200, html.replace(PIN_PLACEHOLDER, room.pin))

    async def _room(self, slug: str, ip: str | None) -> RoomRef | None:
        room = None
        if 0 < len(slug) <= MAX_SLUG_LENGTH:
            room = await self.schedule.room_by_slug(slug)
        if room is None or room.status != "active":
            await self.not_found.count(ip)
            return None
        return room

    def _form(
        self,
        room: RoomRef,
        raw_day: str | None,
        locale: str,
        *,
        wrong: bool,
        status: int,
    ) -> WebResponse:
        html = self.renderer.render(
            "pin_form",
            locale,
            {"room_name": room.name, "day": raw_day or "", "wrong": wrong},
        )
        return WebResponse(status, html)

    async def _day_html(self, room: RoomRef, day: date, today: date) -> str:
        cached = await self.cache.get(room.slug, day)
        if cached is not None:
            return cached
        html = await self._render_day(room, day, today)
        await self.cache.put(room.slug, day, html)
        return html

    async def _render_day(self, room: RoomRef, day: date, today: date) -> str:
        lessons = await self.schedule.room_day(room.id, day)
        resources = await self._resources([lesson.id for lesson in lessons])
        teacher_ids = list({item.teacher_id for item in lessons if item.teacher_id})
        teachers = await self.identity.get_users(teacher_ids) if teacher_ids else {}
        model = self.day_builder.build(
            room,
            day,
            today=today,
            now=self.clock.now(),
            lessons=lessons,
            resources=resources,
            teachers=teachers,
        )
        return self.renderer.render("room", "en", {"day": model})

    async def _resources(
        self, lesson_ids: list[UUID]
    ) -> dict[UUID, list[ResourceView]]:
        if not lesson_ids:
            return {}
        async with self.uow_factory() as uow:
            links = await uow.links.list_for_lessons(lesson_ids)
        visible = [
            link for link in links if link.is_listed_resource(include_hidden=False)
        ]
        views = await self.builder.resources(visible)
        grouped: dict[UUID, list[ResourceView]] = {}
        for view in views:
            assert view.link.lesson_id is not None
            grouped.setdefault(view.link.lesson_id, []).append(view)
        return grouped
