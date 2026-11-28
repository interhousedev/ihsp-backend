"""Clubs, members, ownership transfers, course links and the team."""

from dataclasses import dataclass, fields
from typing import Any
from uuid import UUID

from app.interfaces.http.v1.activities.deps import (
    ActorDep,
    ContainerDep,
    IdOut,
    ItemsOut,
    LeftOut,
    StatusOut,
    items,
)
from app.modules.activities.application.memberships import MemberView
from app.modules.activities.domain.club import Club
from app.modules.activities.domain.course_link import ClubCourseLink
from app.modules.activities.domain.errors import ActivitiesNotFoundError
from app.modules.activities.domain.membership import Membership
from app.modules.activities.domain.ownership import OwnershipTransfer
from app.modules.activities.domain.team import (
    PositionApplication,
    TeamPosition,
    TeamSeat,
)

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/activities", tags=["activities"])


class ClubIn(BaseModel):
    """Create a club draft."""

    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(min_length=1, max_length=60)
    description: str = Field(default="", max_length=4000)


class ClubPatch(BaseModel):
    """Editable club fields; only the sent ones change."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=4000)
    join_policy: str | None = None
    visibility_public: bool | None = None
    contact_enabled: bool | None = None
    logo_file_id: UUID | None = None
    category: str | None = Field(default=None, max_length=40)
    goals: str | None = Field(default=None, max_length=4000)
    rules: str | None = Field(default=None, max_length=4000)
    schedule: str | None = Field(default=None, max_length=4000)
    partners: list[str] | None = Field(default=None, max_length=20)


@dataclass(slots=True)
class ClubOut(Club):
    """A club with the served address of its logo."""

    logo_url: str | None = None


def club_logo_url(club: Club) -> str | None:
    """API-relative logo link of a club; null when it has no logo."""
    if club.logo_file_id is None:
        return None
    return f"/v1/activities/clubs/{club.id}/logo?v={club.logo_file_id}"


def club_out(club: Club) -> ClubOut:
    """The club with its logo link."""
    data = {f.name: getattr(club, f.name) for f in fields(club)}
    return ClubOut(**data, logo_url=club_logo_url(club))


class ClubListItem(BaseModel):
    """A club in the directory."""

    club: ClubOut
    member_count: int
    my_role: str | None
    my_status: str | None


class MyClubOut(BaseModel):
    """The caller's place and rights in one club."""

    club_id: UUID
    role: str | None
    status: str | None
    is_member: bool
    is_organizer: bool
    can_edit: bool
    can_manage_events: bool
    can_view_members: bool
    can_approve: bool


class JoinIn(BaseModel):
    """Join request."""

    message: str | None = Field(default=None, max_length=1000)


class BanIn(BaseModel):
    """Ban reason."""

    reason: str = Field(default="", max_length=500)


class TransferIn(BaseModel):
    """Offer the club to a person."""

    to_user_id: UUID


class CourseLinkIn(BaseModel):
    """Link the club to an LMS course."""

    course_id: UUID


class PositionIn(BaseModel):
    """A team position."""

    title: Any
    description: Any = None
    slots: int = Field(default=1, ge=1)
    open_for_applications: bool = True
    form_schema: dict[str, Any] = Field(default_factory=dict)


class ApplyIn(BaseModel):
    """Application answers."""

    answers: dict[str, Any] = Field(default_factory=dict)


class NoteIn(BaseModel):
    """A short note."""

    note: str | None = Field(default=None, max_length=1000)


class ConsentIn(BaseModel):
    """Public-page consent of a team seat."""

    granted: bool


class PublicIn(BaseModel):
    """Show or hide a seat on the public page."""

    public: bool


@router.post("/clubs", status_code=status.HTTP_201_CREATED)
async def create_club(
    body: ClubIn, container: ContainerDep, actor: ActorDep
) -> StatusOut:
    """Start a club as a draft."""
    club = await container.activities.clubs.create(
        actor, body.name, body.slug, body.description
    )
    return StatusOut(id=str(club.id), status=str(club.status))


@router.get("/clubs")
async def list_clubs(
    container: ContainerDep, actor: ActorDep
) -> ItemsOut[ClubListItem]:
    """Active public clubs and the caller's own, with member counts."""
    rows = await container.activities.clubs.directory(actor)
    return items(
        ClubListItem(
            club=club_out(r.club),
            member_count=r.member_count,
            my_role=r.my_role,
            my_status=r.my_status,
        )
        for r in rows
    )


@router.get("/clubs/mine")
async def my_clubs(container: ContainerDep, actor: ActorDep) -> ItemsOut[Club]:
    """Clubs the caller belongs to."""
    return items(await container.activities.clubs.list_mine(actor))


@router.get("/clubs/{club_id}")
async def get_club(club_id: UUID, container: ContainerDep, actor: ActorDep) -> ClubOut:
    """One club."""
    return club_out(await container.activities.clubs.get(actor, club_id))


@router.get(
    "/clubs/{club_id}/logo",
    response_class=Response,
    responses={200: {"content": {"image/*": {}}}},
)
async def club_logo(
    club_id: UUID, container: ContainerDep, v: UUID | None = None
) -> Response:
    """The logo of an active public club; anonymous, since it is public info."""
    club = await container.activities.public.get_active_club(club_id)
    if club.logo_file_id is None:
        raise ActivitiesNotFoundError()
    data = await container.files.public.read_bytes(club.logo_file_id)
    return Response(
        data,
        media_type=_image_type(data),
        headers={"Cache-Control": "public, max-age=86400"},
    )


def _image_type(data: bytes) -> str:
    """Sniff PNG, JPEG or WebP; anything else is served as a binary blob."""
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


@router.get("/clubs/{club_id}/me")
async def my_club_state(
    club_id: UUID, container: ContainerDep, actor: ActorDep
) -> MyClubOut:
    """The caller's membership, role and staff flags in a club."""
    st = await container.activities.clubs.my_state(actor, club_id)
    return MyClubOut(
        club_id=st.club_id,
        role=st.role,
        status=st.status,
        is_member=st.is_member,
        is_organizer=st.is_organizer,
        can_edit=st.can_edit,
        can_manage_events=st.can_manage_events,
        can_view_members=st.can_view_members,
        can_approve=st.can_approve,
    )


@router.patch("/clubs/{club_id}")
async def update_club(
    club_id: UUID, body: ClubPatch, container: ContainerDep, actor: ActorDep
) -> Club:
    """Edit a club."""
    club = await container.activities.clubs.update(
        actor, club_id, **body.model_dump(exclude_unset=True)
    )
    return club


@router.post("/clubs/{club_id}:submit")
async def submit_club(club_id: UUID, container: ContainerDep, actor: ActorDep) -> Club:
    """Send the draft to review."""
    return await container.activities.clubs.submit(actor, club_id)


@router.post("/clubs/{club_id}/join")
async def join_club(
    club_id: UUID, container: ContainerDep, actor: ActorDep, body: JoinIn | None = None
) -> Membership:
    """Join or ask to join."""
    message = body.message if body else None
    return await container.activities.memberships.join(actor, club_id, message)


@router.post("/clubs/{club_id}/leave")
async def leave_club(
    club_id: UUID, container: ContainerDep, actor: ActorDep
) -> LeftOut:
    """Leave a club."""
    await container.activities.memberships.leave(actor, club_id)
    return LeftOut()


@router.get("/clubs/{club_id}/members")
async def members(
    club_id: UUID, container: ContainerDep, actor: ActorDep
) -> ItemsOut[MemberView]:
    """Members of a club."""
    return items(await container.activities.memberships.members(actor, club_id))


@router.post("/clubs/{club_id}/members/{user_id}:approve")
async def approve_member(
    club_id: UUID, user_id: UUID, container: ContainerDep, actor: ActorDep
) -> Membership:
    """Accept a join request."""
    return await container.activities.memberships.approve(actor, club_id, user_id)


@router.post("/clubs/{club_id}/members/{user_id}:ban")
async def ban_member(
    club_id: UUID,
    user_id: UUID,
    body: BanIn,
    container: ContainerDep,
    actor: ActorDep,
) -> Membership:
    """Remove and ban a member."""
    return await container.activities.memberships.ban(
        actor, club_id, user_id, body.reason
    )


@router.post("/clubs/{club_id}/transfers", status_code=status.HTTP_201_CREATED)
async def offer_transfer(
    club_id: UUID, body: TransferIn, container: ContainerDep, actor: ActorDep
) -> OwnershipTransfer:
    """Offer ownership of the club."""
    return await container.activities.ownership.offer(actor, club_id, body.to_user_id)


@router.get("/transfers/incoming")
async def incoming_transfers(
    container: ContainerDep, actor: ActorDep
) -> list[OwnershipTransfer]:
    """Open ownership offers addressed to the caller."""
    return await container.activities.ownership.incoming(actor)


@router.post("/transfers/{transfer_id}:accept")
async def accept_transfer(
    transfer_id: UUID, container: ContainerDep, actor: ActorDep
) -> OwnershipTransfer:
    """Accept an offer."""
    return await container.activities.ownership.accept(actor, transfer_id)


@router.post("/transfers/{transfer_id}:decline")
async def decline_transfer(
    transfer_id: UUID, container: ContainerDep, actor: ActorDep
) -> OwnershipTransfer:
    """Decline an offer."""
    return await container.activities.ownership.decline(actor, transfer_id)


@router.post("/transfers/{transfer_id}:cancel")
async def cancel_transfer(
    transfer_id: UUID, container: ContainerDep, actor: ActorDep
) -> OwnershipTransfer:
    """Withdraw an offer."""
    return await container.activities.ownership.cancel(actor, transfer_id)


@router.post("/clubs/{club_id}/courses", status_code=status.HTTP_201_CREATED)
async def request_course(
    club_id: UUID, body: CourseLinkIn, container: ContainerDep, actor: ActorDep
) -> ClubCourseLink:
    """Ask to link a course (the other side confirms)."""
    return await container.activities.club_courses.request(
        actor, club_id, body.course_id
    )


@router.post("/clubs/{club_id}/courses/{course_id}:confirm")
async def confirm_course(
    club_id: UUID, course_id: UUID, container: ContainerDep, actor: ActorDep
) -> ClubCourseLink:
    """Confirm a requested link."""
    return await container.activities.club_courses.confirm(actor, club_id, course_id)


@router.delete(
    "/clubs/{club_id}/courses/{course_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def unlink_course(
    club_id: UUID, course_id: UUID, container: ContainerDep, actor: ActorDep
) -> Response:
    """Remove a link."""
    await container.activities.club_courses.unlink(actor, club_id, course_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/clubs/{club_id}/courses")
async def club_courses(
    club_id: UUID, container: ContainerDep, actor: ActorDep
) -> ItemsOut[ClubCourseLink]:
    """Courses linked to a club."""
    return items(await container.activities.club_courses.for_club(actor, club_id))


@router.get("/courses/{course_id}/clubs")
async def course_clubs(
    course_id: UUID, container: ContainerDep, actor: ActorDep
) -> ItemsOut[ClubCourseLink]:
    """Clubs linked to a course."""
    return items(await container.activities.club_courses.for_course(actor, course_id))


@router.post("/clubs/{club_id}/positions", status_code=status.HTTP_201_CREATED)
async def create_position(
    club_id: UUID, body: PositionIn, container: ContainerDep, actor: ActorDep
) -> TeamPosition:
    """Open a team position."""
    return await container.activities.team.create_position(
        actor, club_id, **body.model_dump()
    )


@router.get("/clubs/{club_id}/positions")
async def list_positions(
    club_id: UUID, container: ContainerDep, actor: ActorDep
) -> ItemsOut[TeamPosition]:
    """Team positions."""
    return items(await container.activities.team.list_positions(club_id))


@router.post("/positions/{position_id}/applications", status_code=201)
async def apply_position(
    position_id: UUID, body: ApplyIn, container: ContainerDep, actor: ActorDep
) -> PositionApplication:
    """Apply for a position."""
    return await container.activities.team.apply(actor, position_id, body.answers)


@router.get("/positions/{position_id}/applications")
async def position_applications(
    position_id: UUID, container: ContainerDep, actor: ActorDep
) -> ItemsOut[PositionApplication]:
    """Applications to a position."""
    return items(await container.activities.team.applications(actor, position_id))


@router.post("/applications/{application_id}:shortlist")
async def shortlist(
    application_id: UUID, container: ContainerDep, actor: ActorDep
) -> PositionApplication:
    """Shortlist an application."""
    return await container.activities.team.shortlist(actor, application_id)


@router.post("/applications/{application_id}:reject")
async def reject(
    application_id: UUID, body: NoteIn, container: ContainerDep, actor: ActorDep
) -> PositionApplication:
    """Reject an application."""
    return await container.activities.team.reject(actor, application_id, body.note)


@router.post("/applications/{application_id}:accept")
async def accept(
    application_id: UUID, container: ContainerDep, actor: ActorDep
) -> TeamSeat:
    """Accept an application."""
    return await container.activities.team.accept(actor, application_id)


@router.post("/applications/{application_id}:withdraw")
async def withdraw(
    application_id: UUID, container: ContainerDep, actor: ActorDep
) -> PositionApplication:
    """Withdraw own application."""
    return await container.activities.team.withdraw(actor, application_id)


@router.put("/me/seats/{seat_id}/public-consent")
async def set_consent(
    seat_id: UUID, body: ConsentIn, container: ContainerDep, actor: ActorDep
) -> TeamSeat:
    """The seat holder's own consent to appear publicly."""
    return await container.activities.team.set_consent(actor, seat_id, body.granted)


@router.put("/seats/{seat_id}/public")
async def set_public(
    seat_id: UUID, body: PublicIn, container: ContainerDep, actor: ActorDep
) -> TeamSeat:
    """Show or hide a seat on the public page."""
    return await container.activities.team.set_public(actor, seat_id, body.public)


__all__ = ["IdOut", "router"]
