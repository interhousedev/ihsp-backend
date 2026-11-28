"""Public club pages and the contact form (`/v1/public/clubs`)."""

from typing import Annotated, Any

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_client_ip, get_container
from app.interfaces.http.errors import problem_body, problem_response
from app.shared.base_error import RateLimitedError

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/public/clubs", tags=["public-clubs"])

ContainerDep = Annotated[Container, Depends(get_container)]


class PublicClubOut(BaseModel):
    """A club as the public sees it; no person ids, no addresses."""

    id: str
    slug: str
    name: Any
    description: str
    logo_url: str | None
    contact_enabled: bool
    join_policy: str


class PublicTeamMemberOut(BaseModel):
    """A consenting team member shown on the public page."""

    name: str
    position: Any
    bio: Any
    photo_url: str | None


class PublicClubPageOut(PublicClubOut):
    """A club page with its public team and the contact form's Turnstile key."""

    team: list[PublicTeamMemberOut]
    captcha_site_key: str


class PublicClubListOut(BaseModel):
    """Public clubs and the public Turnstile key of the contact form."""

    items: list[PublicClubOut]
    captcha_site_key: str


class ContactIn(BaseModel):
    """A visitor's message to the club."""

    name: str = Field(min_length=1, max_length=120)
    email: str = Field(
        min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    )
    message: str = Field(min_length=1, max_length=2000)
    captcha_token: str = Field(default="", max_length=4000)
    website: str | None = Field(default=None, max_length=500)


class ContactOut(BaseModel):
    """Accepted for delivery."""

    status: str = "accepted"


def _club(c: Any, contact_open: bool) -> PublicClubOut:
    logo = (
        f"/v1/activities/clubs/{c.id}/logo?v={c.logo_file_id}"
        if c.logo_file_id
        else None
    )
    return PublicClubOut(
        id=str(c.id),
        slug=c.slug,
        name=c.name,
        description=c.description,
        logo_url=logo,
        contact_enabled=contact_open,
        join_policy=str(c.join_policy),
    )


@router.get("")
async def list_clubs(container: ContainerDep) -> PublicClubListOut:
    """Active public clubs."""
    public = container.activities.public
    items = [_club(c, await public.contact_open(c)) for c in await public.list_clubs()]
    return PublicClubListOut(
        items=items,
        captcha_site_key=container.settings.activities.turnstile_site_key,
    )


@router.get("/{slug}")
async def get_club(slug: str, container: ContainerDep) -> PublicClubPageOut:
    """One club page."""
    svc = container.activities
    club = await svc.public.get_club(slug)
    team = await svc.team.public_team(club.id)
    return PublicClubPageOut(
        **_club(club, await svc.public.contact_open(club)).model_dump(),
        team=team,
        captcha_site_key=container.settings.activities.turnstile_site_key,
    )


@router.post(
    "/{slug}/contact",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ContactOut,
    responses={
        409: {"description": "The club owner cannot receive messages"},
        429: {"description": "Too many messages; see Retry-After"},
    },
)
async def contact(
    slug: str,
    body: ContactIn,
    request: Request,
    container: ContainerDep,
    ip: Annotated[str | None, Depends(get_client_ip)],
) -> ContactOut | JSONResponse:
    """Send a message to the club owner on Telegram; nothing is stored."""
    try:
        await container.activities.public.submit_contact(
            slug,
            name=body.name,
            email=body.email,
            message=body.message,
            captcha_token=body.captcha_token,
            honeypot=body.website or "",
            ip=ip or "unknown",
        )
    except RateLimitedError as exc:
        response = problem_response(exc.status, problem_body(request, exc))
        response.headers["Retry-After"] = str(exc.params.get("retry_after", 60))
        return response
    return ContactOut()


ROUTERS: list[APIRouter] = [router]
