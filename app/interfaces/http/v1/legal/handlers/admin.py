"""Administrator routes under /v1/admin/legal."""

from app.interfaces.http.v1.legal.deps import AdminActor, AppScopeQuery, ContainerDep
from app.interfaces.http.v1.legal.schemas import (
    AcceptanceCountOut,
    AcceptanceCountsOut,
    AdminDocumentListOut,
    AdminDocumentOut,
    DraftIn,
    LegalKindValue,
    OverviewOut,
)


async def list_all(container: ContainerDep, actor: AdminActor) -> AdminDocumentListOut:
    """Every version of every kind."""
    documents = await container.legal.list_all.execute()
    return AdminDocumentListOut(items=[AdminDocumentOut.of(d) for d in documents])


async def overview(container: ContainerDep, actor: AdminActor) -> OverviewOut:
    """Documents grouped by app scope with versions and acceptance counts."""
    return OverviewOut.of(await container.legal.overview.execute())


async def save_draft(
    kind: LegalKindValue,
    body: DraftIn,
    container: ContainerDep,
    actor: AdminActor,
    app_scope: AppScopeQuery = "global",
) -> AdminDocumentOut:
    """Create or replace the draft of the kind in the scope."""
    draft = await container.legal.save_draft.execute(
        kind,
        title=body.title,
        body_markdown=body.body_markdown,
        announcement=body.announcement,
        app_scope=app_scope,
    )
    return AdminDocumentOut.of(draft)


async def publish(
    kind: LegalKindValue,
    container: ContainerDep,
    actor: AdminActor,
    app_scope: AppScopeQuery = "global",
) -> AdminDocumentOut:
    """Publish the draft: every user of the scope has to accept it."""
    published = await container.legal.publish.execute(
        kind, actor_id=actor.user_id, app_scope=app_scope
    )
    return AdminDocumentOut.of(published)


async def acceptance_counts(
    container: ContainerDep, actor: AdminActor
) -> AcceptanceCountsOut:
    """Acceptances of the current version of each published kind."""
    counts = await container.legal.count_acceptances.execute()
    return AcceptanceCountsOut(items=[AcceptanceCountOut.of(c) for c in counts])
