"""Guest essay review through a link (`/v1/public/admission/essay-review/*`)."""

import datetime as dt
from collections.abc import Callable, Coroutine
from typing import Annotated, Any
from uuid import UUID

from app.interfaces.http.dependencies import get_client_ip
from app.interfaces.http.v1.admission.deps import ContainerDep
from app.interfaces.http.v1.admission.routes_essay_invites import AudienceT
from app.interfaces.http.v1.admission.routes_exemplars import ProblemOut
from app.modules.admission.application.essay_invites import CommentDraft, FeedbackView
from app.modules.admission.domain.essay_invites import AUTHOR_MAX, BODY_MAX, QUOTE_MAX

from fastapi import APIRouter, Depends, Request, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field

_PRIVATE_HEADERS: dict[str, str] = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex",
}
_TOKEN_MAX = 200


async def _handled(request: Request, exc: Exception) -> Response:
    """Answer an error with the app's own exception handler."""
    handlers = request.app.exception_handlers
    for kind in type(exc).__mro__:
        handler = handlers.get(kind)
        if handler is not None:
            out: Response = await handler(request, exc)
            return out
    raise exc


class PrivateRoute(APIRoute):
    """A route whose every answer, errors too, is private and unindexed."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        """Wrap the handler so the headers reach error answers as well."""
        inner = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                response = await inner(request)
            except Exception as exc:  # noqa: BLE001 - answered by the app handler
                response = await _handled(request, exc)
            response.headers.update(_PRIVATE_HEADERS)
            return response

        return handler


router = APIRouter(
    prefix="/v1/public/admission/essay-review",
    tags=["admission-public"],
    route_class=PrivateRoute,
)

ClientIp = Annotated[str | None, Depends(get_client_ip)]


class OpenIn(BaseModel):
    """The token from the link fragment."""

    token: str = Field(min_length=1, max_length=_TOKEN_MAX)


class CommentIn(BaseModel):
    """A guest comment, optionally anchored to a quoted span."""

    token: str = Field(min_length=1, max_length=_TOKEN_MAX)
    author_name: str = Field(min_length=1, max_length=AUTHOR_MAX)
    body: str = Field(min_length=1, max_length=BODY_MAX)
    quote: str | None = Field(default=None, max_length=QUOTE_MAX)
    anchor_start: int | None = Field(default=None, ge=0)
    anchor_end: int | None = Field(default=None, ge=0)


class GuestEssayOut(BaseModel):
    """The essay as a reviewer sees it, with no owner identity."""

    kind: str
    title: str
    prompt_text: str
    body: str
    word_count: int


class GuestCommentOut(BaseModel):
    """A comment left through this link."""

    id: UUID
    parent_id: UUID | None
    author_name: str
    quote: str | None
    anchor_start: int | None
    anchor_end: int | None
    detached: bool
    body: str
    resolved: bool
    created_at: dt.datetime

    @classmethod
    def of(cls, v: FeedbackView) -> "GuestCommentOut":
        """Build from a placed comment."""
        f = v.item
        return cls(
            id=f.id,
            parent_id=f.parent_id,
            author_name=f.author_name,
            quote=f.quote,
            anchor_start=v.anchor.start,
            anchor_end=v.anchor.end,
            detached=v.anchor.detached,
            body=f.body,
            resolved=f.resolved_at is not None,
            created_at=f.created_at,
        )


class GuestReviewOut(BaseModel):
    """What a link opens: the essay and the comments of this link."""

    essay: GuestEssayOut
    audience: AudienceT
    can_comment: bool
    expires_at: dt.datetime
    comments: list[GuestCommentOut]


async def open_review(
    body: OpenIn, container: ContainerDep, ip: ClientIp
) -> GuestReviewOut:
    """Open an essay through a review link (no account)."""
    view = await container.admission.essay_invites.open(body.token, ip)
    e = view.essay
    return GuestReviewOut(
        essay=GuestEssayOut(
            kind=e.kind,
            title=e.title,
            prompt_text=e.prompt_text or "",
            body=e.body,
            word_count=e.word_count,
        ),
        audience=view.invite.audience,
        can_comment=view.invite.can_comment,
        expires_at=view.invite.expires_at,
        comments=[GuestCommentOut.of(v) for v in view.feedback],
    )


async def add_comment(body: CommentIn, container: ContainerDep) -> GuestCommentOut:
    """Leave a comment through a review link (no account)."""
    draft = CommentDraft(body.body, body.quote, body.anchor_start, body.anchor_end)
    view = await container.admission.essay_invites.comment(
        body.token, body.author_name, draft
    )
    return GuestCommentOut.of(view)


_Responses = dict[int | str, dict[str, Any]]
_GONE: _Responses = {
    404: {"model": ProblemOut, "description": "Unknown, expired or revoked."}
}
_READ_ONLY: _Responses = {
    403: {"model": ProblemOut, "description": "The link is read-only."}
}
_INVALID: _Responses = {
    422: {"model": ProblemOut, "description": "A field breaks a rule."}
}
_LIMITED: _Responses = {429: {"model": ProblemOut, "description": "Too many requests."}}
_SEALED: _Responses = {
    503: {"model": ProblemOut, "description": "The essay key service is down."}
}

router.add_api_route(
    "/open",
    open_review,
    methods=["POST"],
    operation_id="admission_open_essay_review",
    response_model=GuestReviewOut,
    responses={**_GONE, **_INVALID, **_LIMITED, **_SEALED},
)
router.add_api_route(
    "/comments",
    add_comment,
    methods=["POST"],
    operation_id="admission_add_essay_review_comment",
    response_model=GuestCommentOut,
    status_code=201,
    responses={**_READ_ONLY, **_GONE, **_INVALID, **_LIMITED, **_SEALED},
)
