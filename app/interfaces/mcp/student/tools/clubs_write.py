"""Students tools of `clubs:write`: organizers run their club's events and media.

Every permission check (organizer, announcer, uploader, other club) is in the
activities services; these tools only translate arguments and results.
"""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.student.tools.clubs_views import (
    activities,
    announcement_view,
    event_view,
    media_view,
)
from app.interfaces.mcp.toolkit import ToolKit
from app.shared.base_error import ValidationFailedError

from pydantic import Field

SCOPE = "clubs:write"

ClubIdParam = Annotated[UUID, Field(description="The club id.")]
EventIdParam = Annotated[UUID, Field(description="The event id.")]
MediaIdParam = Annotated[UUID, Field(description="The media id.")]
TitleParam = Annotated[str, Field(min_length=1, max_length=200)]
TextParam = Annotated[str | None, Field(max_length=4000)]
CapacityParam = Annotated[int | None, Field(ge=1, description="Omit: no limit.")]
PolicyParam = Literal["open", "members", "approval"]


def register(kit: ToolKit) -> None:  # noqa: C901 - one closure per tool
    """Register the club write tools."""

    @kit.tool(SCOPE, read_only=False, idempotent=False, log=LogSpec(keep=("club_id",)))
    async def create_club_event(
        club_id: ClubIdParam,
        title: TitleParam,
        starts_at: Annotated[datetime, Field(description="ISO time with zone.")],
        ends_at: Annotated[datetime, Field(description="ISO time with zone.")],
        description: TextParam = None,
        location: Annotated[str | None, Field(max_length=300)] = None,
        capacity: CapacityParam = None,
        rsvp_policy: PolicyParam = "open",
    ) -> dict[str, Any]:
        """Create a draft event of a club the student organizes.

        Publish it with publish_club_event.
        """
        event = await activities(kit).events.create(
            current_actor(),
            club_id,
            title,
            starts_at,
            ends_at,
            capacity,
            rsvp_policy,
            description=description,
            location=location,
        )
        return {"event": event_view(event)}

    @kit.tool(SCOPE, read_only=False, idempotent=True, log=LogSpec(keep=("event_id",)))
    async def update_club_event(
        event_id: EventIdParam,
        title: Annotated[str | None, Field(min_length=1, max_length=200)] = None,
        description: TextParam = None,
        location: Annotated[str | None, Field(max_length=300)] = None,
        capacity: CapacityParam = None,
        rsvp_policy: PolicyParam | None = None,
    ) -> dict[str, Any]:
        """Edit the texts, capacity or RSVP policy of a draft or scheduled event.

        Omitted fields stay as they are; the time is not changed here.
        """
        event = await activities(kit).events.update(
            current_actor(),
            event_id,
            title=title,
            description=description,
            location=location,
            capacity=capacity,
            rsvp_policy=rsvp_policy,
        )
        return {"event": event_view(event)}

    @kit.tool(SCOPE, read_only=False, idempotent=False, log=LogSpec(keep=("event_id",)))
    async def publish_club_event(event_id: EventIdParam) -> dict[str, Any]:
        """Publish a draft event: members see it and reminders are planned."""
        event = await activities(kit).events.publish(current_actor(), event_id)
        return {"event": event_view(event)}

    @kit.tool(
        SCOPE,
        read_only=False,
        destructive=True,
        idempotent=False,
        log=LogSpec(keep=("event_id",)),
    )
    async def cancel_club_event(event_id: EventIdParam) -> dict[str, Any]:
        """Cancel an event; participants are told."""
        event = await activities(kit).events.cancel(current_actor(), event_id)
        return {"event": event_view(event)}

    @kit.tool(
        SCOPE,
        read_only=False,
        idempotent=False,
        log=LogSpec(keep=("club_id", "media_id")),
    )
    async def upload_club_media(
        club_id: ClubIdParam,
        media_id: Annotated[
            UUID | None,
            Field(description="Step 2: the media_id of step 1 after the PUT."),
        ] = None,
        name: Annotated[str | None, Field(max_length=200)] = None,
        size: Annotated[int | None, Field(ge=1, description="Bytes.")] = None,
        content_type: Annotated[
            str | None, Field(description="image/jpeg, image/png, video/mp4 ...")
        ] = None,
        sha256_b64: Annotated[
            str | None, Field(description="Base64 SHA-256 of the file.")
        ] = None,
        consent_attested: Annotated[
            bool,
            Field(description="Everyone recognisable agreed to be published."),
        ] = False,
        caption: Annotated[str | None, Field(max_length=300)] = None,
    ) -> dict[str, Any]:
        """Upload a photo or video for a club in two steps.

        Step 1 (no media_id): give name, size, content_type, sha256_b64 and
        consent_attested; PUT the bytes to upload_url with upload_headers.
        Step 2: call again with media_id to finish. The item stays staged until it
        is used as a cover, an announcement photo or added to an event.
        """
        actor = current_actor()
        media = activities(kit).media
        if media_id is not None:
            return {"media": media_view(await media.complete(actor, media_id))}
        if name is None or size is None or content_type is None or not sha256_b64:
            raise ValidationFailedError(
                params={"field": "name, size, content_type, sha256_b64"}
            )
        started = await media.request_upload(
            actor,
            club_id,
            name=name,
            size=size,
            content_type=content_type,
            sha256_b64=sha256_b64,
            consent_attested=consent_attested,
            caption=caption,
        )
        return {
            "media_id": str(started.media.id),
            "upload_url": started.upload_url,
            "upload_method": started.upload_method,
            "upload_headers": started.upload_headers,
        }

    @kit.tool(
        SCOPE,
        read_only=False,
        idempotent=True,
        log=LogSpec(keep=("event_id", "media_id")),
    )
    async def set_event_cover(
        event_id: EventIdParam,
        media_id: Annotated[
            UUID | None, Field(description="A ready photo; omit to remove the cover.")
        ] = None,
    ) -> dict[str, Any]:
        """Use an uploaded photo of the club as the event cover."""
        event = await activities(kit).events.set_cover(
            current_actor(), event_id, media_id
        )
        return {"event": event_view(event)}

    @kit.tool(
        SCOPE,
        read_only=False,
        idempotent=True,
        log=LogSpec(keep=("event_id", "media_id")),
    )
    async def add_event_media(
        event_id: EventIdParam, media_id: MediaIdParam
    ) -> dict[str, Any]:
        """Put an uploaded photo or video into the event's album."""
        actor = current_actor()
        media = activities(kit).media
        album = await media.ensure_event_album(actor, event_id)
        view = await media.attach(actor, media_id, album.album.id)
        return {"album_id": str(album.album.id), "media": media_view(view)}

    @kit.tool(SCOPE, read_only=False, idempotent=False, log=LogSpec(keep=("club_id",)))
    async def send_club_announcement(
        club_id: ClubIdParam,
        text: Annotated[str, Field(min_length=1, max_length=4000)],
        audience: Annotated[
            str, Field(description="members, team or event:<event_id>.")
        ] = "members",
        scheduled_at: Annotated[
            datetime | None, Field(description="Omit to send now.")
        ] = None,
        media_ids: Annotated[
            list[UUID], Field(max_length=10, description="Uploaded photos to attach.")
        ] = [],  # noqa: B006 - pydantic copies the default
    ) -> dict[str, Any]:
        """Send an announcement to the club, now or at a set time, with photos."""
        ann = await activities(kit).announcements.send(
            current_actor(), club_id, text, audience, scheduled_at, media_ids
        )
        return {"announcement": announcement_view(ann)}

    @kit.tool(
        SCOPE,
        read_only=False,
        destructive=True,
        idempotent=False,
        log=LogSpec(keep=("announcement_id",)),
    )
    async def cancel_club_announcement(
        announcement_id: Annotated[UUID, Field(description="The announcement id.")],
    ) -> dict[str, Any]:
        """Withdraw a scheduled announcement that was not sent yet."""
        ann = await activities(kit).announcements.cancel(
            current_actor(), announcement_id
        )
        return {"announcement": announcement_view(ann)}

    @kit.tool(
        SCOPE,
        read_only=False,
        destructive=True,
        idempotent=True,
        log=LogSpec(keep=("media_id",)),
    )
    async def delete_club_media(media_id: MediaIdParam) -> dict[str, Any]:
        """Delete a photo or video you uploaded, or any if you moderate the club."""
        await activities(kit).media.delete(current_actor(), media_id)
        return {"media_id": str(media_id), "deleted": True}
