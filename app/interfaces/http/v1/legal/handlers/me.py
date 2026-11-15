"""Signed-in routes: GET /v1/me/legal/pending, POST /v1/me/legal/accept."""

from typing import Annotated

from app.interfaces.http.dependencies import get_client_ip
from app.interfaces.http.v1.legal.deps import ContainerDep, Locale, UserActor
from app.interfaces.http.v1.legal.schemas import AcceptIn, PendingOut
from app.shared.contracts.legal import LegalItem

from fastapi import Depends, Request


async def get_pending(
    container: ContainerDep, actor: UserActor, locale: Locale
) -> PendingOut:
    """Current documents the user has not accepted yet."""
    items = await container.legal.pending.execute(actor.user_id)
    return PendingOut.of(items, locale)


async def accept(
    body: AcceptIn,
    request: Request,
    container: ContainerDep,
    actor: UserActor,
    locale: Locale,
    ip: Annotated[str | None, Depends(get_client_ip)],
) -> PendingOut:
    """Accept current versions; stale ones answer 409. Returns what is left."""
    items = await container.legal.accept.execute(
        actor.user_id,
        [LegalItem(i.kind, i.version) for i in body.items],
        ip=ip,
        user_agent=request.headers.get("user-agent"),
    )
    return PendingOut.of(items, locale)
