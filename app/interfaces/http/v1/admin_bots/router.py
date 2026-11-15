"""Routes /v1/admin/bots: the Telegram bot registry (admin only)."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.interfaces.http.v1.admin_bots.schemas import (
    AnnouncementBody,
    AnnouncementOut,
    BotCreateBody,
    BotOut,
    BotPatchBody,
    BotsResponse,
    BotTokenBody,
)
from app.modules.admin.domain.telegram_bot import parse_features
from app.shared.actor import Actor, Role

from fastapi import APIRouter, Depends, status

router = APIRouter(prefix="/v1/admin/bots", tags=["admin-bots"])

ContainerDep = Annotated[Container, Depends(get_container)]
AdminActor = Annotated[Actor, Depends(require_roles(Role.ADMIN))]


@router.get("", response_model=BotsResponse)
async def list_bots(container: ContainerDep, actor: AdminActor) -> BotsResponse:
    """Every registered bot with its feature switches and member count."""
    views = await container.admin.bot_admin.list_bots(actor)
    return BotsResponse(items=[BotOut.of(view) for view in views])


@router.post("", response_model=BotOut, status_code=status.HTTP_201_CREATED)
async def add_bot(
    body: BotCreateBody, container: ContainerDep, actor: AdminActor
) -> BotOut:
    """Register a bot; it starts with every feature off (bot process restart).

    Needs a fresh step-up code (403 ``identity/step-up-invalid``).
    """
    view = await container.admin.bot_admin.add(
        actor, name=body.name, token=body.token, otp_code=body.otp_code
    )
    return BotOut.of(view)


@router.post("/announcements", response_model=AnnouncementOut)
async def announce(
    body: AnnouncementBody, container: ContainerDep, actor: AdminActor
) -> AnnouncementOut:
    """Send a draft broadcast through the selected bots; needs step-up."""
    result = await container.admin.bot_admin.announce(
        actor, body.broadcast_id, body.bot_ids, otp_code=body.otp_code
    )
    return AnnouncementOut.of(result)


@router.patch("/{bot_id}", response_model=BotOut)
async def update_bot(
    bot_id: UUID, body: BotPatchBody, container: ContainerDep, actor: AdminActor
) -> BotOut:
    """Rename, switch on or off, or change feature switches; needs step-up."""
    features = None if body.features is None else parse_features(body.features)
    view = await container.admin.bot_admin.update(
        actor,
        bot_id,
        name=body.name,
        enabled=body.enabled,
        features=features,
        otp_code=body.otp_code,
    )
    return BotOut.of(view)


@router.post("/{bot_id}/rotate-token", response_model=BotOut)
async def rotate_token(
    bot_id: UUID, body: BotTokenBody, container: ContainerDep, actor: AdminActor
) -> BotOut:
    """Replace the token of the same Telegram bot; needs step-up."""
    view = await container.admin.bot_admin.rotate_token(
        actor, bot_id, body.token, otp_code=body.otp_code
    )
    return BotOut.of(view)
