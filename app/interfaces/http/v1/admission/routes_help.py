"""Routes of help requests, the helper directory and guest links."""

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from app.interfaces.http.v1.admission.deps import (
    AdmissionCtx,
    ContainerDep,
    HelperCtx,
)
from app.modules.admission.application.guest import CreatedGuestLink
from app.modules.admission.application.help import HelpDetail
from app.modules.admission.domain.help_proofs import (
    GuestLinkRecord,
    HelperActivity,
    HelperDirectoryEntry,
    HelpResponse,
)
from app.modules.admission.domain.workflow import HelpRequest

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/admission", tags=["admission"])

HelpKindIn = Literal["website", "design", "proof", "other"]


class HelpRequestIn(BaseModel):
    """A new request; `helper_user_id` addresses a directory helper."""

    kind: HelpKindIn
    brief: str = Field(min_length=1, max_length=2000)
    item_id: UUID | None = None
    helper_user_id: UUID | None = None
    expires_in_days: int | None = Field(default=None, ge=1, le=60)


class AssignIn(BaseModel):
    """The helper to address."""

    helper_user_id: UUID


class HelpRequestOut(BaseModel):
    """A help request."""

    id: UUID
    student_id: UUID
    kind: str
    brief: str
    status: str
    item_id: UUID | None
    helper_user_id: UUID | None
    expires_at: datetime

    @classmethod
    def of(cls, r: HelpRequest) -> "HelpRequestOut":
        """Build from the domain request."""
        return cls(
            id=r.id,
            student_id=r.student_id,
            kind=r.kind,
            brief=r.brief,
            status=r.status,
            item_id=r.item_id,
            helper_user_id=r.helper_user_id,
            expires_at=r.expires_at,
        )


class HelpRequestListOut(BaseModel):
    """Help requests."""

    items: list[HelpRequestOut]


class HelpResponseIn(BaseModel):
    """A response of a helper."""

    text: str = Field(min_length=1, max_length=4000)
    url: str | None = Field(default=None, max_length=2048)
    file_id: UUID | None = None


class HelpResponseOut(BaseModel):
    """A response to a request."""

    id: UUID
    help_request_id: UUID
    text: str
    url: str | None
    file_id: UUID | None
    from_guest: bool
    created_at: datetime

    @classmethod
    def of(cls, r: HelpResponse) -> "HelpResponseOut":
        """Build from the domain response."""
        return cls(
            id=r.id,
            help_request_id=r.help_request_id,
            text=r.text,
            url=r.url,
            file_id=r.file_id,
            from_guest=r.guest_link_id is not None,
            created_at=r.created_at,
        )


class MetricOut(BaseModel):
    """One reduced metric."""

    label: str
    value: str
    unit: str | None


class HelperActivityOut(BaseModel):
    """What a helper may see of an activity: no grades, essays or contacts."""

    position: str
    org: str
    description: str
    kind: str
    metrics: list[MetricOut]

    @classmethod
    def of(cls, a: HelperActivity) -> "HelperActivityOut":
        """Build from the reduced domain activity."""
        return cls(
            position=a.position,
            org=a.org,
            description=a.description,
            kind=a.kind,
            metrics=[
                MetricOut(label=m.label, value=m.value, unit=m.unit)
                for m in a.current_metrics
            ],
        )


class HelpDetailOut(BaseModel):
    """A request with its responses; activities only for the helper."""

    request: HelpRequestOut
    responses: list[HelpResponseOut]
    activities: list[HelperActivityOut] | None
    as_helper: bool

    @classmethod
    def of(cls, d: HelpDetail) -> "HelpDetailOut":
        """Build from the use-case result."""
        return cls(
            request=HelpRequestOut.of(d.request),
            responses=[HelpResponseOut.of(r) for r in d.responses],
            activities=(
                None
                if d.activities is None
                else [HelperActivityOut.of(a) for a in d.activities]
            ),
            as_helper=d.as_helper,
        )


class HelperOut(BaseModel):
    """A helper in the directory."""

    user_id: UUID
    display_name: str


class HelperListOut(BaseModel):
    """Directory matches."""

    items: list[HelperOut]


class GuestLinkIn(BaseModel):
    """A new guest link (also creates its help request)."""

    label: str | None = Field(default=None, max_length=80)
    help_request_id: UUID | None = None
    item_id: UUID | None = None
    kind: HelpKindIn = "other"
    brief: str = Field(default="", max_length=2000)
    expires_in_days: int | None = Field(default=None, ge=1, le=60)


class GuestLinkOut(BaseModel):
    """A guest link without its token."""

    id: UUID
    help_request_id: UUID
    label: str | None
    token_prefix: str
    scope: list[str]
    expires_at: datetime
    max_sessions: int
    sessions_used: int
    revoked_at: datetime | None
    last_used_at: datetime | None
    claimed: bool

    @classmethod
    def of(cls, r: GuestLinkRecord) -> "GuestLinkOut":
        """Build from the stored record."""
        link = r.link
        return cls(
            id=link.id,
            help_request_id=link.help_request_id,
            label=r.label,
            token_prefix=link.token_prefix,
            scope=list(link.scope),
            expires_at=link.expires_at,
            max_sessions=link.max_sessions,
            sessions_used=link.sessions_used,
            revoked_at=link.revoked_at,
            last_used_at=r.last_used_at,
            claimed=r.claimed_by is not None,
        )


class GuestLinkListOut(BaseModel):
    """The student's guest links."""

    items: list[GuestLinkOut]


class CreatedGuestLinkOut(BaseModel):
    """A new link; the token is shown once."""

    link: GuestLinkOut
    token: str
    help_request_id: UUID

    @classmethod
    def of(cls, c: CreatedGuestLink) -> "CreatedGuestLinkOut":
        """Build from the created link."""
        return cls(
            link=GuestLinkOut.of(c.record),
            token=c.token,
            help_request_id=c.help_request_id,
        )


class ClaimIn(BaseModel):
    """A guest token to attach to the caller's account."""

    token: str = Field(min_length=8, max_length=200)


async def create_help_request(
    body: HelpRequestIn, container: ContainerDep, ctx: AdmissionCtx
) -> HelpRequestOut:
    """Ask a mentor, counselor or helper for help."""
    r = await container.admission.help.create(
        ctx,
        body.kind,
        body.brief,
        item_id=body.item_id,
        helper_user_id=body.helper_user_id,
        expires_in_days=body.expires_in_days,
    )
    return HelpRequestOut.of(r)


async def list_help_requests(
    container: ContainerDep, ctx: AdmissionCtx
) -> HelpRequestListOut:
    """The student's help requests."""
    rows = await container.admission.help.list_own(ctx)
    return HelpRequestListOut(items=[HelpRequestOut.of(r) for r in rows])


async def get_help_request(
    request_id: UUID, container: ContainerDep, ctx: HelperCtx
) -> HelpDetailOut:
    """One request: the owner sees responses, the helper a reduced view."""
    return HelpDetailOut.of(await container.admission.help.get(ctx, request_id))


async def assign_help_request(
    request_id: UUID, body: AssignIn, container: ContainerDep, ctx: AdmissionCtx
) -> HelpRequestOut:
    """Address the request to a directory helper."""
    r = await container.admission.help.assign(ctx, request_id, body.helper_user_id)
    return HelpRequestOut.of(r)


async def cancel_help_request(
    request_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> HelpRequestOut:
    """Withdraw the request."""
    return HelpRequestOut.of(await container.admission.help.cancel(ctx, request_id))


async def close_help_request(
    request_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> HelpRequestOut:
    """Close a delivered request."""
    return HelpRequestOut.of(await container.admission.help.close(ctx, request_id))


async def accept_help_request(
    request_id: UUID, container: ContainerDep, ctx: HelperCtx
) -> HelpRequestOut:
    """The addressed helper accepts."""
    return HelpRequestOut.of(await container.admission.help.accept(ctx, request_id))


async def decline_help_request(
    request_id: UUID, container: ContainerDep, ctx: HelperCtx
) -> HelpRequestOut:
    """The addressed helper declines."""
    return HelpRequestOut.of(await container.admission.help.decline(ctx, request_id))


async def deliver_help_request(
    request_id: UUID, container: ContainerDep, ctx: HelperCtx
) -> HelpRequestOut:
    """The helper marks the help as delivered."""
    return HelpRequestOut.of(await container.admission.help.deliver(ctx, request_id))


async def respond_help_request(
    request_id: UUID,
    body: HelpResponseIn,
    container: ContainerDep,
    ctx: HelperCtx,
) -> HelpResponseOut:
    """The helper answers."""
    r = await container.admission.help.respond(
        ctx, request_id, body.text, url=body.url, file_id=body.file_id
    )
    return HelpResponseOut.of(r)


async def search_helpers(
    container: ContainerDep,
    ctx: AdmissionCtx,
    q: str = Query(min_length=1, max_length=60),
) -> HelperListOut:
    """Find opted-in helpers by display name."""
    rows: list[HelperDirectoryEntry] = await container.admission.help.search_helpers(
        ctx, q
    )
    return HelperListOut(
        items=[HelperOut(user_id=h.user_id, display_name=h.display_name) for h in rows]
    )


async def list_assigned_help(
    container: ContainerDep, ctx: HelperCtx
) -> HelpRequestListOut:
    """Requests addressed to the caller."""
    rows = await container.admission.help.list_assigned(ctx)
    return HelpRequestListOut(items=[HelpRequestOut.of(r) for r in rows])


async def create_guest_link(
    body: GuestLinkIn, container: ContainerDep, ctx: AdmissionCtx
) -> CreatedGuestLinkOut:
    """Create a guest link for an outside helper; the token is shown once."""
    created = await container.admission.guest.create(
        ctx,
        label=body.label,
        help_request_id=body.help_request_id,
        item_id=body.item_id,
        kind=body.kind,
        brief=body.brief,
        expires_in_days=body.expires_in_days,
    )
    return CreatedGuestLinkOut.of(created)


async def list_guest_links(
    container: ContainerDep, ctx: AdmissionCtx
) -> GuestLinkListOut:
    """The student's guest links."""
    rows = await container.admission.guest.list(ctx)
    return GuestLinkListOut(items=[GuestLinkOut.of(r) for r in rows])


async def revoke_guest_link(
    link_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> None:
    """Revoke a guest link."""
    await container.admission.guest.revoke(ctx, link_id)


async def rotate_guest_link(
    link_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> CreatedGuestLinkOut:
    """Replace a link with a new token; the old one stops working."""
    return CreatedGuestLinkOut.of(await container.admission.guest.rotate(ctx, link_id))


async def claim_guest_link(
    body: ClaimIn, container: ContainerDep, ctx: HelperCtx
) -> HelpRequestOut:
    """Attach a guest link's request to the caller's account."""
    return HelpRequestOut.of(await container.admission.guest.claim(ctx, body.token))


def _route(
    path: str,
    fn: Callable[..., Awaitable[Any]],
    method: str,
    out: type[BaseModel] | None,
    op: str,
    code: int = 200,
) -> None:
    router.add_api_route(
        path,
        fn,
        methods=[method],
        response_model=out,
        status_code=code,
        operation_id=op,
    )


_route(
    "/help-requests",
    create_help_request,
    "POST",
    HelpRequestOut,
    "admission_create_help_request",
    status.HTTP_201_CREATED,
)
_route(
    "/help-requests",
    list_help_requests,
    "GET",
    HelpRequestListOut,
    "admission_list_help_requests",
)
_route(
    "/help-requests/{request_id}",
    get_help_request,
    "GET",
    HelpDetailOut,
    "admission_get_help_request",
)
_route(
    "/help-requests/{request_id}/assign",
    assign_help_request,
    "POST",
    HelpRequestOut,
    "admission_assign_help_request",
)
_route(
    "/help-requests/{request_id}/cancel",
    cancel_help_request,
    "POST",
    HelpRequestOut,
    "admission_cancel_help_request",
)
_route(
    "/help-requests/{request_id}/close",
    close_help_request,
    "POST",
    HelpRequestOut,
    "admission_close_help_request",
)
_route(
    "/help-requests/{request_id}/accept",
    accept_help_request,
    "POST",
    HelpRequestOut,
    "admission_accept_help_request",
)
_route(
    "/help-requests/{request_id}/decline",
    decline_help_request,
    "POST",
    HelpRequestOut,
    "admission_decline_help_request",
)
_route(
    "/help-requests/{request_id}/deliver",
    deliver_help_request,
    "POST",
    HelpRequestOut,
    "admission_deliver_help_request",
)
_route(
    "/help-requests/{request_id}/responses",
    respond_help_request,
    "POST",
    HelpResponseOut,
    "admission_respond_help_request",
    status.HTTP_201_CREATED,
)
_route(
    "/help/helpers", search_helpers, "GET", HelperListOut, "admission_search_helpers"
)
_route(
    "/help/assigned",
    list_assigned_help,
    "GET",
    HelpRequestListOut,
    "admission_list_assigned_help",
)
_route(
    "/guest-links",
    create_guest_link,
    "POST",
    CreatedGuestLinkOut,
    "admission_create_guest_link",
    status.HTTP_201_CREATED,
)
_route(
    "/guest-links",
    list_guest_links,
    "GET",
    GuestLinkListOut,
    "admission_list_guest_links",
)
_route(
    "/guest-links/claim",
    claim_guest_link,
    "POST",
    HelpRequestOut,
    "admission_claim_guest_link",
)
_route(
    "/guest-links/{link_id}",
    revoke_guest_link,
    "DELETE",
    None,
    "admission_revoke_guest_link",
    status.HTTP_204_NO_CONTENT,
)
_route(
    "/guest-links/{link_id}/rotate",
    rotate_guest_link,
    "POST",
    CreatedGuestLinkOut,
    "admission_rotate_guest_link",
    status.HTTP_201_CREATED,
)
