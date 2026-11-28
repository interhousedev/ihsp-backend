"""Administration of clubs, analytics and the one opportunities catalog."""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.interfaces.http.v1.activities.clubs import club_logo_url
from app.interfaces.http.v1.activities.schemas_media import (
    BlockOut,
    MediaOut,
    ReportOut,
    UsageOut,
)
from app.interfaces.http.v1.admin_activities.schemas import (
    AdminClubCreateIn,
    AdminClubListOut,
    AdminClubOut,
    AnalyticsOut,
    ArchiveIn,
    BlockIn,
    BlockListOut,
    CapabilitiesIn,
    ForceTransferIn,
    HideIn,
    MediaLimitsIn,
    OpportunityIn,
    OpportunityListOut,
    OpportunityOut,
    ReasonIn,
    ReviewIn,
    ReviewItemOut,
    ReviewListOut,
    TransferredOut,
)
from app.modules.activities.domain.club import Club, ClubCapability, ClubStatus
from app.shared.actor import Actor, Role

from fastapi import APIRouter, Depends, Query, Response, status

router = APIRouter(prefix="/v1/admin/activities", tags=["admin-activities"])

ContainerDep = Annotated[Container, Depends(get_container)]
Curator = Annotated[Actor, Depends(require_roles(Role.ADMIN, Role.ACTIVITIES_ADMIN))]
Moderator = Annotated[
    Actor,
    Depends(require_roles(Role.SU, Role.ACTIVITIES_ADMIN, Role.ADMIN)),
]
Superuser = Annotated[Actor, Depends(require_roles(Role.SU))]


@router.get("/clubs")
async def list_clubs(
    container: ContainerDep,
    actor: Moderator,
    status_: Annotated[ClubStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AdminClubListOut:
    """Every club of any status, with owner and member count."""
    rows, total = await container.activities.clubs.list_admin(
        actor, status_, limit, offset
    )
    return AdminClubListOut(
        items=[
            AdminClubOut(
                id=r.club.id,
                slug=r.club.slug,
                name=r.club.name,
                status=str(r.club.status),
                kind=str(r.club.kind),
                owner_id=r.club.owner_id,
                owner_name=r.owner_name,
                member_count=r.member_count,
                logo_url=club_logo_url(r.club),
            )
            for r in rows
        ],
        total=total,
    )


@router.post("/clubs", status_code=status.HTTP_201_CREATED)
async def create_club(
    body: AdminClubCreateIn, container: ContainerDep, actor: Superuser
) -> Club:
    """Create an approved club owned by the given person."""
    return await container.activities.clubs.create_active(
        actor, body.name, body.slug, body.description, body.owner_user_id
    )


@router.post("/clubs/{club_id}:resume")
async def resume_club(club_id: UUID, container: ContainerDep, actor: Moderator) -> Club:
    """Bring a suspended club back."""
    return await container.activities.clubs.resume(actor, club_id)


@router.post("/clubs/{club_id}:review")
async def review_club(
    club_id: UUID, body: ReviewIn, container: ContainerDep, actor: Superuser
) -> Club:
    """Approve a club or send it back with a reason."""
    club = await container.activities.clubs.review(
        actor, club_id, body.approve, body.reason
    )
    return club


@router.post("/clubs/{club_id}:suspend")
async def suspend_club(
    club_id: UUID, body: ReasonIn, container: ContainerDep, actor: Superuser
) -> Club:
    """Suspend a club."""
    return await container.activities.clubs.suspend(actor, club_id, body.reason)


@router.post("/clubs/{club_id}:force-transfer")
async def force_transfer(
    club_id: UUID, body: ForceTransferIn, container: ContainerDep, actor: Superuser
) -> TransferredOut:
    """Hand a club to another person without an offer."""
    await container.activities.ownership.force_transfer(actor, club_id, body.to_user_id)
    return TransferredOut()


@router.put("/clubs/{club_id}/capabilities")
async def set_capabilities(
    club_id: UUID, body: CapabilitiesIn, container: ContainerDep, actor: Moderator
) -> Club:
    """Switch club features (forms, drafting, points) on or off."""
    caps = {ClubCapability(c) for c in body.capabilities}
    return await container.activities.clubs.set_capabilities(actor, club_id, caps)


@router.get("/analytics")
async def analytics(
    container: ContainerDep,
    actor: Moderator,
    since: datetime | None = None,
    until: datetime | None = None,
) -> AnalyticsOut:
    """Platform-wide club figures."""
    return AnalyticsOut.model_validate(
        await container.activities.analytics.overview(actor, since, until)
    )


@router.post("/opportunities", status_code=status.HTTP_201_CREATED)
async def create_opportunity(
    body: OpportunityIn, container: ContainerDep, actor: Curator
) -> OpportunityOut:
    """Add an entry to the one catalog."""
    entry = await container.activities.opportunities.create(
        actor, body.kind, body.title, frozenset(body.audience), **body.extra()
    )
    return OpportunityOut.of(entry)


@router.get("/opportunities")
async def list_opportunities(
    container: ContainerDep, actor: Curator, include_archived: bool = False
) -> OpportunityListOut:
    """Every entry of both audiences."""
    svc = container.activities.opportunities
    seen: dict[UUID, Any] = {}
    for surface in ("admission", "my_iht"):
        for e in await svc.list(actor, surface):
            seen.setdefault(e.id, e)
    rows = [e for e in seen.values() if include_archived or not e.archived]
    return OpportunityListOut(items=[OpportunityOut.of(e) for e in rows])


@router.patch("/opportunities/{opportunity_id}")
async def update_opportunity(
    opportunity_id: UUID,
    body: OpportunityIn,
    container: ContainerDep,
    actor: Curator,
) -> OpportunityOut:
    """Overwrite an entry; a stale `lock_version` conflicts."""
    entry = await container.activities.opportunities.update(
        actor,
        opportunity_id,
        body.kind,
        body.title,
        frozenset(body.audience),
        lock_version=body.lock_version if body.lock_version is not None else -1,
        **body.extra(),
    )
    return OpportunityOut.of(entry)


@router.post("/opportunities/{opportunity_id}:archive")
async def archive_opportunity(
    opportunity_id: UUID, body: ArchiveIn, container: ContainerDep, actor: Curator
) -> OpportunityOut:
    """Hide or restore an entry."""
    entry = await container.activities.opportunities.archive(
        actor, opportunity_id, body.archived
    )
    return OpportunityOut.of(entry)


@router.delete(
    "/opportunities/{opportunity_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_opportunity(
    opportunity_id: UUID, container: ContainerDep, actor: Curator
) -> Response:
    """Delete an unused entry."""
    await container.activities.opportunities.delete(actor, opportunity_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/media")
async def media_queue(
    container: ContainerDep,
    actor: Moderator,
    state: Annotated[Literal["reported", "hidden"], Query()] = "reported",
    club_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ReviewListOut:
    """Club media awaiting review: reported or hidden items with their reports."""
    page = await container.activities.media.review_queue(
        actor, state=state, club_id=club_id, limit=limit, offset=offset
    )
    return ReviewListOut(
        items=[
            ReviewItemOut(
                media=MediaOut.of(v),
                reports=[ReportOut.of(r) for r in page.reports.get(v.media.id, [])],
            )
            for v in page.items
        ],
        total=page.total,
    )


@router.post("/media/{media_id}:hide")
async def hide_media(
    media_id: UUID, body: HideIn, container: ContainerDep, actor: Moderator
) -> MediaOut:
    """Hide an item from everyone but moderators."""
    return MediaOut.of(
        await container.activities.media.set_hidden(
            actor, media_id, True, body.reason or None
        )
    )


@router.post("/media/{media_id}:restore")
async def restore_media(
    media_id: UUID, container: ContainerDep, actor: Moderator
) -> MediaOut:
    """Show a hidden item again."""
    return MediaOut.of(
        await container.activities.media.set_hidden(actor, media_id, False)
    )


@router.delete("/media/{media_id}", status_code=status.HTTP_204_NO_CONTENT)
async def purge_media(
    media_id: UUID, container: ContainerDep, actor: Moderator
) -> Response:
    """Remove an item and its files now."""
    await container.activities.media.purge_now(actor, media_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/media-reports/{report_id}:dismiss")
async def dismiss_report(
    report_id: UUID, container: ContainerDep, actor: Moderator
) -> MediaOut:
    """Close a report as unfounded; the item returns when no report stays open."""
    return MediaOut.of(
        await container.activities.media.resolve_report(actor, report_id, upheld=False)
    )


@router.post("/media-reports/{report_id}:uphold")
async def uphold_report(
    report_id: UUID, container: ContainerDep, actor: Moderator
) -> MediaOut:
    """Agree with a report; the item stays hidden."""
    return MediaOut.of(
        await container.activities.media.resolve_report(actor, report_id, upheld=True)
    )


@router.get("/media-blocks")
async def list_media_blocks(
    container: ContainerDep, actor: Moderator, club_id: UUID | None = None
) -> BlockListOut:
    """Upload blocks of a club, or the global ones."""
    rows = await container.activities.media.list_blocks(actor, club_id)
    return BlockListOut(items=[BlockOut.of(b) for b in rows])


@router.post("/media-blocks", status_code=status.HTTP_201_CREATED)
async def block_uploader(
    body: BlockIn, container: ContainerDep, actor: Moderator
) -> BlockOut:
    """Bar a user from uploading club media."""
    block = await container.activities.media.block_uploader(
        actor, body.user_id, club_id=body.club_id, reason=body.reason
    )
    return BlockOut.of(block)


@router.delete("/media-blocks/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unblock_uploader(
    user_id: UUID,
    container: ContainerDep,
    actor: Moderator,
    club_id: UUID | None = None,
) -> Response:
    """Lift an upload block."""
    await container.activities.media.unblock_uploader(actor, user_id, club_id=club_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/clubs/{club_id}/media-limits")
async def get_media_limits(
    club_id: UUID, container: ContainerDep, actor: Moderator
) -> UsageOut:
    """Storage use, limits in force and the club's overrides."""
    return UsageOut.of(await container.activities.media.usage(actor, club_id))


@router.put("/clubs/{club_id}/media-limits")
async def set_media_limits(
    club_id: UUID, body: MediaLimitsIn, container: ContainerDep, actor: Moderator
) -> UsageOut:
    """Replace the club's overrides; a null field falls back to the default."""
    usage = await container.activities.media.set_club_limits(
        actor, club_id, **body.model_dump()
    )
    return UsageOut.of(usage)


@router.delete("/clubs/{club_id}/media-limits")
async def clear_media_limits(
    club_id: UUID, container: ContainerDep, actor: Moderator
) -> UsageOut:
    """Drop every override of the club."""
    return UsageOut.of(await container.activities.media.set_club_limits(actor, club_id))
