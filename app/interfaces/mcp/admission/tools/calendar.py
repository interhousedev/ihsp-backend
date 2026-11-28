"""Calendar tools: dated events of the caller's plans, `.ics` export and the feed.

Event UIDs are the feed's, so an event exported twice (or exported and also
subscribed to) is the same event to a calendar client that honours UIDs. The
feed URL is a bearer secret: it is shown only by create/replace, never by
get_calendar_feed, and never written to the call log.
"""

import datetime as dt
from typing import Annotated, Any, Literal

from app.interfaces.mcp.admission.tools.common import Locale, applicant, services
from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.constants import WRITE_LIMIT
from app.interfaces.mcp.errors import McpInvalidInputError
from app.interfaces.mcp.toolkit import ToolKit
from app.interfaces.mcp.untrusted import mark_untrusted
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.calendar import (
    MAX_EXPORT_KEYS,
    MAX_RANGE_DAYS,
)
from app.modules.admission.domain.calendar import CalendarEntry, entry_uid
from app.shared.base_error import ConflictError
from app.shared.mcp_scopes import ADMISSION_APPLICANT_ROLES

from pydantic import Field

ROLES = ADMISSION_APPLICANT_ROLES
TIMEZONE = "Asia/Tashkent"
ICS_MAX_BYTES = 256 * 1024
_UNTRUSTED_SOURCES = frozenset({"personal", "milestone"})

Source = Literal[
    "university",
    "checklist",
    "exam",
    "opportunity",
    "test_score",
    "personal",
    "milestone",
]
Day = Annotated[dt.date, Field(description="YYYY-MM-DD, Tashkent time.")]


class FeedExistsError(ConflictError):
    """A live feed exists; replacing it is replace_calendar_feed."""

    code = "admission/feed_exists"
    message_key = "calendar-feed-exists"


def _event(e: CalendarEntry, user_key: str, alarms: tuple[int, ...]) -> dict[str, Any]:
    return {
        "uid": entry_uid(user_key, e.key),
        "key": e.key,
        "source": e.source,
        "title": e.title,
        "start": e.day if e.all_day else e.due_utc,
        "end": e.day if e.all_day else e.due_utc,
        "all_day": e.all_day,
        "timezone": TIMEZONE,
        "url_path": e.url_path,
        "predicted": e.predicted,
        "description": e.description,
        "alarm_days_before": list(alarms),
        "untrusted": e.source in _UNTRUSTED_SOURCES,
    }


def register(kit: ToolKit) -> None:  # noqa: C901 - one closure per tool
    """Register the calendar tools."""

    def _cal() -> Any:
        # Resolved per call: deps.admission is unset when the server is built
        # without the admission module (tests, processes without admission).
        return services(kit).calendar

    async def _user_key(ctx: AdmissionContext) -> str:
        feed = await _cal().store.active_feed(ctx.user_id)
        return str(feed.id.hex if feed else ctx.user_id.hex)

    def _urls(path: str) -> dict[str, str]:
        https_url = kit.deps.settings.urls.api.rstrip("/") + path
        webcal = "webcal://" + https_url.split("://", 1)[-1]
        return {"https_url": https_url, "webcal_url": webcal}

    @kit.tool("calendar:read", roles=ROLES)
    async def get_calendar(
        start: Day,
        end: Day,
        sources: Annotated[
            list[Source] | None, Field(max_length=7, description="Only these.")
        ] = None,
        locale: Locale = "en",
    ) -> dict[str, Any]:
        """Dated events of the student's plans between two days (at most 400).

        Universities, checklist, exams, saved opportunities, test scores, own
        finds (`personal`, unverified) and goal milestones. Use the `key`s with
        export_calendar_ics. If the student also subscribes to the feed, do not
        create the same events again in another calendar.
        """
        ctx = await applicant(kit)
        rows = await _cal().entries(ctx, start, end, locale)
        if sources:
            rows = [e for e in rows if e.source in sources]
        alarms = (await _cal().feed_status(ctx)).alarm_offsets
        key = await _user_key(ctx)
        events = [_event(e, key, alarms) for e in rows]
        return mark_untrusted({"events": events}, "events[].title")

    @kit.tool("calendar:read", roles=ROLES)
    async def export_calendar_ics(
        keys: Annotated[
            list[str] | None,
            Field(
                max_length=MAX_EXPORT_KEYS,
                description="Event keys from get_calendar (at most 50).",
            ),
        ] = None,
        start: Annotated[
            dt.date | None, Field(description="Without keys: first day.")
        ] = None,
        end: Annotated[
            dt.date | None,
            Field(description=f"Without keys: last day (at most {MAX_RANGE_DAYS})."),
        ] = None,
        locale: Locale = "en",
    ) -> dict[str, Any]:
        """An `.ics` file (text) of chosen events, or of all events in a range.

        UIDs match the student's feed, so importing it twice updates the same
        events in clients that honour UIDs.
        """
        ctx = await applicant(kit)
        ics = await _cal().export(
            ctx, locale, keys=tuple(keys or ()), start=start, end=end
        )
        if len(ics.encode()) > ICS_MAX_BYTES:
            raise McpInvalidInputError(params={"reason": "too many events"})
        return {
            "filename": "admission-calendar.ics",
            "content_type": "text/calendar",
            "ics": ics,
        }

    @kit.tool("calendar:read", roles=ROLES)
    async def get_calendar_feed() -> dict[str, Any]:
        """Whether the student has a live calendar subscription; never its URL."""
        ctx = await applicant(kit)
        status = await _cal().feed_status(ctx)
        return {
            "active": status.active,
            "created_at": status.created_at,
            "alarm_days_before": list(status.alarm_offsets),
        }

    @kit.tool(
        "calendar:write",
        read_only=False,
        idempotent=False,
        limit=WRITE_LIMIT,
        log=LogSpec(keep=("locale",)),
        roles=ROLES,
    )
    async def create_calendar_feed(locale: Locale = "en") -> dict[str, Any]:
        """Create the subscription URL; only when no live feed exists.

        The URL is shown this once and works like a password: anyone with it
        sees the dates. With a live feed this answers `feed_exists`; use
        replace_calendar_feed only if the student wants a new URL.
        """
        ctx = await applicant(kit)
        if (await _cal().feed_status(ctx)).active:
            raise FeedExistsError()
        issued = await _cal().issue_feed(ctx, locale)
        return _urls(issued.path)

    @kit.tool(
        "calendar:write",
        read_only=False,
        destructive=True,
        idempotent=False,
        limit=WRITE_LIMIT,
        log=LogSpec(keep=("locale",)),
        roles=ROLES,
    )
    async def replace_calendar_feed(locale: Locale = "en") -> dict[str, Any]:
        """Issue a new subscription URL; the old one stops working at once."""
        ctx = await applicant(kit)
        issued = await _cal().issue_feed(ctx, locale)
        return _urls(issued.path)

    @kit.tool(
        "calendar:write",
        read_only=False,
        destructive=True,
        idempotent=True,
        limit=WRITE_LIMIT,
        log=LogSpec(),
        roles=ROLES,
    )
    async def revoke_calendar_feed() -> dict[str, Any]:
        """Stop the subscription; calendars that use it get no more updates."""
        ctx = await applicant(kit)
        await _cal().revoke_feed(ctx)
        return {"active": False}
