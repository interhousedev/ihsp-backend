"""Media links issued through MCP: open one, list mine, stop one (MCP-B5)."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import (
    get_actor,
    get_client_ip,
    get_container,
    get_optional_actor,
)
from app.shared.actor import Actor

from fastapi import Depends, Response
from pydantic import BaseModel, Field


class MediaRedeemBody(BaseModel):
    """`POST /v1/lms/media/redeem`: the token from the fragment of the link."""

    token: str = Field(min_length=1, max_length=128)


class MediaRedeemResponse(BaseModel):
    """A short-lived address; nothing about the course on refusal."""

    url: str
    expires_in: int
    title: str
    tier: Literal["anon", "enrolled"]


class MediaGrantItem(BaseModel):
    """A link I issued; the token is never stored, so never shown again."""

    id: UUID
    course_id: UUID
    step_id: UUID
    block_id: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    redeem_count: int


class MediaGrantsResponse(BaseModel):
    """My media links."""

    items: list[MediaGrantItem]


async def redeem_media(
    body: MediaRedeemBody,
    response: Response,
    viewer: Annotated[Actor | None, Depends(get_optional_actor)],
    ip: Annotated[str | None, Depends(get_client_ip)],
    container: Annotated[Container, Depends(get_container)],
) -> MediaRedeemResponse:
    """Open a link: 5 hours anonymously, always when enrolled, never when not."""
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    view = await container.lms.learning.redeem_media_grant.execute(
        body.token, viewer, ip
    )
    tier: Literal["anon", "enrolled"] = (
        "enrolled" if view.tier == "enrolled" else "anon"
    )
    return MediaRedeemResponse(
        url=view.url, expires_in=view.expires_in, title=view.title, tier=tier
    )


async def list_media_grants(
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
) -> MediaGrantsResponse:
    """Return the media links issued for the caller."""
    grants = await container.lms.learning.revoke_media_grants.list_mine(actor)
    return MediaGrantsResponse(
        items=[
            MediaGrantItem(
                id=grant.id,
                course_id=grant.course_id,
                step_id=grant.step_id,
                block_id=grant.block_id,
                created_at=grant.created_at,
                expires_at=grant.expires_at,
                revoked_at=grant.revoked_at,
                redeem_count=grant.redeem_count,
            )
            for grant in grants
        ]
    )


async def revoke_media_grant(
    grant_id: UUID,
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
) -> None:
    """Stop one of the caller's media links at once."""
    await container.lms.learning.revoke_media_grants.revoke(actor, grant_id)
