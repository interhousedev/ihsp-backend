"""Public routes of outside helpers (`/v1/public/admission/guest`).

No account: a guest token (`gst_`) is exchanged for a short session token (`gss_`).
The view holds a first name, the request and reduced activities, nothing else.
"""

from datetime import datetime
from typing import Annotated

from app.interfaces.http.dependencies import get_client_ip
from app.interfaces.http.v1.admission.deps import ContainerDep
from app.interfaces.http.v1.admission.routes_help import (
    HelperActivityOut,
    HelpResponseOut,
)
from app.modules.admission.domain.errors import AdmissionNotFoundError

from fastapi import APIRouter, Depends, Header, Response, status
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/public/admission", tags=["admission-guest"])

Ip = Annotated[str | None, Depends(get_client_ip)]


def _bearer(authorization: str | None) -> str:
    """Return the Bearer token or answer like any unknown link."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AdmissionNotFoundError()
    return authorization[7:].strip()


async def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"


class GuestSessionOut(BaseModel):
    """A session token, shown once."""

    token: str
    expires_at: datetime


class GuestViewOut(BaseModel):
    """What an outside helper sees."""

    first_name: str | None
    kind: str
    brief: str
    status: str
    scope: list[str]
    expires_at: datetime
    activities: list[HelperActivityOut]
    responses: list[HelpResponseOut]


class GuestRespondIn(BaseModel):
    """A guest answer: text and an optional public https link."""

    text: str = Field(min_length=1, max_length=4000)
    url: str | None = Field(default=None, max_length=2048)


async def open_guest_session(
    container: ContainerDep,
    ip: Ip,
    authorization: Annotated[str | None, Header()] = None,
) -> GuestSessionOut:
    """Exchange the link token for a session token."""
    s = await container.admission.guest.redeem(_bearer(authorization), ip)
    return GuestSessionOut(token=s.token, expires_at=s.expires_at)


async def view_guest(
    container: ContainerDep,
    ip: Ip,
    authorization: Annotated[str | None, Header()] = None,
) -> GuestViewOut:
    """The request and the reduced activities."""
    v = await container.admission.guest.view(_bearer(authorization), ip)
    return GuestViewOut(
        first_name=v.first_name,
        kind=v.kind,
        brief=v.brief,
        status=v.status,
        scope=list(v.scope),
        expires_at=v.expires_at,
        activities=[HelperActivityOut.of(a) for a in v.activities],
        responses=[HelpResponseOut.of(r) for r in v.responses],
    )


async def respond_guest(
    body: GuestRespondIn,
    container: ContainerDep,
    ip: Ip,
    authorization: Annotated[str | None, Header()] = None,
) -> HelpResponseOut:
    """Answer the student."""
    r = await container.admission.guest.respond(
        _bearer(authorization), ip, body.text, body.url
    )
    return HelpResponseOut.of(r)


for _path, _fn, _method, _out, _op, _code in (
    (
        "/guest/session",
        open_guest_session,
        "POST",
        GuestSessionOut,
        "admission_open_guest_session",
        status.HTTP_200_OK,
    ),
    (
        "/guest",
        view_guest,
        "GET",
        GuestViewOut,
        "admission_view_guest",
        status.HTTP_200_OK,
    ),
    (
        "/guest/respond",
        respond_guest,
        "POST",
        HelpResponseOut,
        "admission_respond_guest",
        status.HTTP_201_CREATED,
    ),
):
    router.add_api_route(
        _path,
        _fn,
        methods=[_method],
        response_model=_out,
        status_code=_code,
        operation_id=_op,
        dependencies=[Depends(_no_store)],
    )
