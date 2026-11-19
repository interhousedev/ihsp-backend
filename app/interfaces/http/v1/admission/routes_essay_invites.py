"""Essay review links and feedback of the student (`/v1/admission/essays/*`)."""

import datetime as dt
from typing import Any, Literal
from uuid import UUID

from app.interfaces.http.v1.admission.deps import AdmissionCtx, ContainerDep
from app.interfaces.http.v1.admission.routes_exemplars import ProblemOut
from app.modules.admission.application.essay_invites import CommentDraft, FeedbackView
from app.modules.admission.domain.essay_invites import (
    BODY_MAX,
    INVITE_TTL_DAYS,
    LABEL_MAX,
    MAX_TTL_DAYS,
    QUOTE_MAX,
    EssayInvite,
)

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/admission", tags=["admission"])

AudienceT = Literal["classmate", "parent", "counselor", "other"]


class InviteIn(BaseModel):
    """A new review link."""

    audience: AudienceT
    label: str | None = Field(default=None, max_length=LABEL_MAX)
    can_comment: bool = True
    ttl_days: int = Field(default=INVITE_TTL_DAYS, ge=1, le=MAX_TTL_DAYS)


class InviteOut(BaseModel):
    """A review link; the token is never shown again."""

    id: UUID
    audience: AudienceT
    label: str | None
    can_comment: bool
    expires_at: dt.datetime
    revoked_at: dt.datetime | None
    last_opened_at: dt.datetime | None
    created_at: dt.datetime | None
    active: bool

    @classmethod
    def of(cls, i: EssayInvite, now: dt.datetime) -> "InviteOut":
        """Build from the domain link."""
        return cls(
            id=i.id,
            audience=i.audience,
            label=i.label,
            can_comment=i.can_comment,
            expires_at=i.expires_at,
            revoked_at=i.revoked_at,
            last_opened_at=i.last_opened_at,
            created_at=i.created_at,
            active=i.is_active(now),
        )


class InviteCreatedOut(InviteOut):
    """A new link with its plain token, shown this once."""

    token: str


class InviteListOut(BaseModel):
    """The links of an essay."""

    items: list[InviteOut]


class FeedbackOut(BaseModel):
    """A comment placed in the current text."""

    id: UUID
    invite_id: UUID | None
    parent_id: UUID | None
    mine: bool
    author_name: str
    invite_label: str | None
    audience: AudienceT | None
    quote: str | None
    anchor_start: int | None
    anchor_end: int | None
    detached: bool
    body: str
    resolved_at: dt.datetime | None
    created_at: dt.datetime

    @classmethod
    def of(cls, v: FeedbackView) -> "FeedbackOut":
        """Build from the placed comment."""
        f = v.item
        return cls(
            id=f.id,
            invite_id=f.invite_id,
            parent_id=f.parent_id,
            mine=f.invite_id is None and not f.author_name,
            author_name=f.author_name,
            invite_label=v.invite_label,
            audience=f.audience,
            quote=f.quote,
            anchor_start=v.anchor.start,
            anchor_end=v.anchor.end,
            detached=v.anchor.detached,
            body=f.body,
            resolved_at=f.resolved_at,
            created_at=f.created_at,
        )


class FeedbackListOut(BaseModel):
    """Every comment on an essay."""

    items: list[FeedbackOut]


class NoteIn(BaseModel):
    """My own note, or a reply to a comment."""

    body: str = Field(min_length=1, max_length=BODY_MAX)
    quote: str | None = Field(default=None, max_length=QUOTE_MAX)
    anchor_start: int | None = Field(default=None, ge=0)
    anchor_end: int | None = Field(default=None, ge=0)
    parent_id: UUID | None = None


class FeedbackPatchIn(BaseModel):
    """Resolve a comment or open it again."""

    resolved: bool


async def create_invite(
    essay_id: UUID, body: InviteIn, container: ContainerDep, ctx: AdmissionCtx
) -> InviteCreatedOut:
    """Make a review link of my essay; the token is shown only here."""
    made = await container.admission.essay_invites.create(
        ctx,
        essay_id,
        audience=body.audience,
        label=body.label,
        can_comment=body.can_comment,
        ttl_days=body.ttl_days,
    )
    out = InviteOut.of(made.invite, container.clock.now())
    return InviteCreatedOut(**out.model_dump(), token=made.token)


async def list_invites(
    essay_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> InviteListOut:
    """The review links of my essay."""
    rows = await container.admission.essay_invites.invites(ctx, essay_id)
    now = container.clock.now()
    return InviteListOut(items=[InviteOut.of(i, now) for i in rows])


async def revoke_invite(
    essay_id: UUID, invite_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> None:
    """Switch a review link off."""
    await container.admission.essay_invites.revoke(ctx, essay_id, invite_id)


async def list_feedback(
    essay_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> FeedbackListOut:
    """Every comment on my essay, placed in the current text."""
    rows = await container.admission.essay_invites.feedback(ctx, essay_id)
    return FeedbackListOut(items=[FeedbackOut.of(v) for v in rows])


async def add_feedback(
    essay_id: UUID, body: NoteIn, container: ContainerDep, ctx: AdmissionCtx
) -> FeedbackOut:
    """Add my own note or a reply."""
    draft = CommentDraft(body.body, body.quote, body.anchor_start, body.anchor_end)
    view = await container.admission.essay_invites.add_note(
        ctx, essay_id, draft, body.parent_id
    )
    return FeedbackOut.of(view)


async def patch_feedback(
    essay_id: UUID,
    feedback_id: UUID,
    body: FeedbackPatchIn,
    container: ContainerDep,
    ctx: AdmissionCtx,
) -> FeedbackOut:
    """Resolve a comment or open it again."""
    view = await container.admission.essay_invites.set_resolved(
        ctx, essay_id, feedback_id, body.resolved
    )
    return FeedbackOut.of(view)


async def delete_feedback(
    essay_id: UUID, feedback_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> None:
    """Delete a comment with its replies."""
    await container.admission.essay_invites.delete_feedback(ctx, essay_id, feedback_id)


def _route(path: str, endpoint: Any, method: str, op: str, **kw: Any) -> None:
    router.add_api_route(
        path, endpoint, methods=[method], operation_id=f"admission_{op}", **kw
    )


_NOT_FOUND = {404: {"model": ProblemOut, "description": "Not my essay or no such row."}}
_INVALID = {422: {"model": ProblemOut, "description": "A field breaks a rule."}}
_LIMIT = {
    422: {
        "model": ProblemOut,
        "description": "A field breaks a rule, or 20 links are already active.",
    }
}
_SEALED = {503: {"model": ProblemOut, "description": "The essay key service is down."}}
_CREATED = {"status_code": status.HTTP_201_CREATED}
_GONE = {"status_code": status.HTTP_204_NO_CONTENT}
_INVITES = "/essays/{essay_id}/invites"
_FEEDBACK = "/essays/{essay_id}/feedback"

_route(
    _INVITES,
    create_invite,
    "POST",
    "create_essay_invite",
    response_model=InviteCreatedOut,
    responses={**_NOT_FOUND, **_LIMIT, **_SEALED},
    **_CREATED,
)
_route(
    _INVITES,
    list_invites,
    "GET",
    "list_essay_invites",
    response_model=InviteListOut,
    responses={**_NOT_FOUND, **_SEALED},
)
_route(
    f"{_INVITES}/{{invite_id}}",
    revoke_invite,
    "DELETE",
    "revoke_essay_invite",
    responses={**_NOT_FOUND},
    **_GONE,
)
_route(
    _FEEDBACK,
    list_feedback,
    "GET",
    "list_essay_feedback",
    response_model=FeedbackListOut,
    responses={**_NOT_FOUND, **_SEALED},
)
_route(
    _FEEDBACK,
    add_feedback,
    "POST",
    "add_essay_feedback",
    response_model=FeedbackOut,
    responses={**_NOT_FOUND, **_INVALID, **_SEALED},
    **_CREATED,
)
_route(
    f"{_FEEDBACK}/{{feedback_id}}",
    patch_feedback,
    "PATCH",
    "patch_essay_feedback",
    response_model=FeedbackOut,
    responses={**_NOT_FOUND, **_INVALID, **_SEALED},
)
_route(
    f"{_FEEDBACK}/{{feedback_id}}",
    delete_feedback,
    "DELETE",
    "delete_essay_feedback",
    responses={**_NOT_FOUND},
    **_GONE,
)
