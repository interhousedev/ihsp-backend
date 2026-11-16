"""Signed-in routes: GET /v1/me/legal/pending, POST /v1/me/legal/accept."""

from typing import Annotated

from app.interfaces.http.dependencies import get_client_ip
from app.interfaces.http.v1.legal.deps import App, ContainerDep, Locale, UserActor
from app.interfaces.http.v1.legal.schemas import AcceptIn, PendingOut
from app.shared.contracts.legal import LegalItem

from fastapi import Depends, Request


async def get_pending(
    container: ContainerDep, actor: UserActor, locale: Locale, app: App
) -> PendingOut:
    """Current global documents and those of the calling app not yet accepted."""
    items = await container.legal.pending.execute(actor.user_id, app)
    return PendingOut.of(items, locale)


async def accept(
    body: AcceptIn,
    request: Request,
    container: ContainerDep,
    actor: UserActor,
    locale: Locale,
    app: App,
    ip: Annotated[str | None, Depends(get_client_ip)],
) -> PendingOut:
    """Accept current versions; stale ones answer 409. Returns what is left."""
    items = await container.legal.accept.execute(
        actor.user_id,
        [LegalItem(i.kind, i.version, i.app_scope) for i in body.items],
        ip=ip,
        user_agent=request.headers.get("user-agent"),
        app=app,
        roles=[r.value for r in actor.roles],
        guardian_attested=body.guardian_attested,
    )
    return PendingOut.of(items, locale)
