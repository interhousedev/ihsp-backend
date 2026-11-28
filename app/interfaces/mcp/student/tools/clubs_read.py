"""Students tools of `clubs:read`: the student's clubs, their events, news and media."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.student.tools.clubs_views import (
    activities,
    announcement_view,
    club_view,
    event_view,
    media_view,
)
from app.interfaces.mcp.toolkit import ToolKit
from app.interfaces.mcp.untrusted import mark_untrusted
from app.shared.app_map import LOCALES

from pydantic import Field

SCOPE = "clubs:read"

ClubIdParam = Annotated[UUID, Field(description="The club id.")]
EventIdParam = Annotated[UUID, Field(description="The event id.")]


def _text(path: str) -> tuple[str, ...]:
    """A user-authored field that is a plain string or a per-locale mapping."""
    return (path, *(f"{path}.{locale}" for locale in LOCALES))


def _club_fields(prefix: str) -> tuple[str, ...]:
    return (*_text(f"{prefix}.name"), *_text(f"{prefix}.description"))


def _event_fields(prefix: str) -> tuple[str, ...]:
    return (
        *_text(f"{prefix}.title"),
        *_text(f"{prefix}.description"),
        *_text(f"{prefix}.location"),
    )


def register(kit: ToolKit) -> None:
    """Register the club read tools."""

    @kit.tool(SCOPE)
    async def list_my_clubs() -> dict[str, Any]:
        """List the clubs the student is an active member of."""
        clubs = await activities(kit).clubs.list_mine(current_actor())
        return mark_untrusted(
            {"clubs": [club_view(c) for c in clubs]}, *_club_fields("clubs[]")
        )

    @kit.tool(SCOPE)
    async def list_club_events(club_id: ClubIdParam) -> dict[str, Any]:
        """List the events of a club; drafts appear only for its organizers."""
        events = await activities(kit).events.list_for_club(current_actor(), club_id)
        return mark_untrusted(
            {"events": [event_view(e) for e in events]}, *_event_fields("events[]")
        )

    @kit.tool(SCOPE)
    async def get_club_event(event_id: EventIdParam) -> dict[str, Any]:
        """Read one club event."""
        event = await activities(kit).events.get(current_actor(), event_id)
        return mark_untrusted({"event": event_view(event)}, *_event_fields("event"))

    @kit.tool(SCOPE)
    async def list_club_announcements(club_id: ClubIdParam) -> dict[str, Any]:
        """List a club's announcements; only for those who may send them."""
        rows = await activities(kit).announcements.list(current_actor(), club_id)
        return mark_untrusted(
            {"announcements": [announcement_view(a) for a in rows]},
            "announcements[].text",
        )

    @kit.tool(SCOPE)
    async def list_event_media(
        event_id: EventIdParam,
        cursor: Annotated[
            str | None, Field(description="next_cursor of the previous page.")
        ] = None,
        limit: Annotated[int, Field(ge=1, le=200)] = 50,
    ) -> dict[str, Any]:
        """List the photos and videos of an event's album, a page at a time."""
        actor = current_actor()
        media = activities(kit).media
        album = await media.event_album(actor, event_id)
        if album is None:
            return {"album_id": None, "items": [], "next_cursor": None}
        page = await media.list_media(actor, album.album.id, cursor=cursor, limit=limit)
        return mark_untrusted(
            {
                "album_id": str(album.album.id),
                "items": [media_view(v) for v in page.items],
                "next_cursor": page.next_cursor,
            },
            "items[].caption",
        )
