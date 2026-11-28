"""Shared plumbing of the student club tools: the services and the result views."""

from typing import Any

from app.interfaces.mcp.jsonable import to_jsonable
from app.interfaces.mcp.toolkit import ToolKit


def activities(kit: ToolKit) -> Any:  # noqa: ANN401 - ActivitiesServices
    """The activities services; a process without them cannot serve club tools."""
    services = kit.deps.activities
    if services is None or not hasattr(services, "events"):
        raise RuntimeError("activities services are not wired into the MCP deps")
    return services


def club_view(club: Any) -> dict[str, Any]:  # noqa: ANN401 - Club
    """One club, without member data."""
    return {
        "club_id": str(club.id),
        "slug": club.slug,
        "name": to_jsonable(club.name),
        "kind": str(club.kind),
        "status": str(club.status),
        "description": club.description,
    }


def event_view(event: Any) -> dict[str, Any]:  # noqa: ANN401 - Event
    """One event."""
    return {
        "event_id": str(event.id),
        "club_id": str(event.club_id),
        "title": to_jsonable(event.title),
        "description": to_jsonable(event.description),
        "location": event.location,
        "starts_at": event.starts_at.isoformat(),
        "ends_at": event.ends_at.isoformat(),
        "capacity": event.capacity,
        "rsvp_policy": str(event.rsvp_policy),
        "status": str(event.status),
        "cover_media_id": str(event.cover_media_id) if event.cover_media_id else None,
    }


def announcement_view(ann: Any) -> dict[str, Any]:  # noqa: ANN401 - Announcement
    """One announcement."""
    return {
        "announcement_id": str(ann.id),
        "club_id": str(ann.club_id),
        "text": ann.text,
        "audience": ann.audience,
        "scheduled_at": ann.scheduled_at.isoformat() if ann.scheduled_at else None,
        "sent_at": ann.sent_at.isoformat() if ann.sent_at else None,
        "recipient_count": ann.recipient_count,
        "cancelled": ann.cancelled,
    }


def media_view(view: Any) -> dict[str, Any]:  # noqa: ANN401 - MediaView
    """One media item with its signed relative URLs."""
    media = view.media
    return {
        "media_id": str(media.id),
        "club_id": str(media.club_id),
        "kind": str(media.kind),
        "status": str(media.status),
        "usage": str(media.usage),
        "album_id": str(media.album_id) if media.album_id else None,
        "caption": media.caption,
        "width": media.width,
        "height": media.height,
        "duration_ms": media.duration_ms,
        "thumb_url": view.thumb_url,
        "preview_url": view.preview_url,
        "video_url": view.video_url,
        "can_delete": view.can_delete,
    }
