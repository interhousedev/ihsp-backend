"""Points, drafting, club forms and opportunities on my.iht."""

import datetime as dt
from typing import Annotated, Any
from uuid import UUID

from app.interfaces.http.v1.activities.deps import (
    ActorDep,
    AttendanceRow,
    ContainerDep,
    ItemsOut,
    LeaderRowOut,
    MyPointsOut,
    OptOutOut,
    items,
)
from app.interfaces.http.v1.admin_activities.schemas import (
    OpportunityListOut,
    OpportunityOut,
)
from app.modules.activities.domain.draft import (
    ClubProfile,
    DraftPick,
    DraftRound,
    DraftSignup,
)
from app.modules.activities.domain.ranking import Ranked

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/activities", tags=["activities"])

SURFACE = "my_iht"


class OptOutIn(BaseModel):
    """Hide the caller from leaderboards."""

    opted_out: bool


class ProfileIn(BaseModel):
    """The member's answers to the club's form."""

    answers: dict[str, Any] = Field(default_factory=dict)


class FormFieldIn(BaseModel):
    """One question of a club form."""

    key: str = Field(min_length=1, max_length=60)
    label: Any
    type: str = "text"
    required: bool = False
    options: list[Any] = Field(default_factory=list)


class FormFieldsIn(BaseModel):
    """The club's whole form."""

    fields: list[FormFieldIn] = Field(max_length=30)


class FormFieldsOut(BaseModel):
    """The club's form questions."""

    fields: list[dict[str, Any]]


class MemberAnswersOut(BaseModel):
    """One member's stored answers."""

    user_id: UUID
    display_name: str
    answers: dict[str, Any]
    updated_at: dt.datetime


class PointsRulesIn(BaseModel):
    """Points per kind of activity."""

    rules: dict[str, int]


class PointsRulesOut(BaseModel):
    """Effective points per kind of activity."""

    rules: dict[str, int]


class AwardIn(BaseModel):
    """A manual award or deduction."""

    user_id: UUID
    points: int = Field(ge=-100, le=100)
    reason: str = Field(min_length=1, max_length=60)


class AwardOut(BaseModel):
    """The stored manual entry."""

    user_id: UUID
    points: int
    reason: str


class RoundIn(BaseModel):
    """Open a drafting round for an event."""

    club_id: UUID
    needed: dict[str, int]


class SignupIn(BaseModel):
    """Sign up for a role."""

    role: str = Field(max_length=60)
    answers: dict[str, Any] = Field(default_factory=dict)


class PickIn(BaseModel):
    """Pick a person for a role."""

    user_id: UUID
    role: str = Field(max_length=60)


class RespondIn(BaseModel):
    """Accept or decline a pick."""

    accept: bool


@router.get("/leaderboard")
async def leaderboard(
    container: ContainerDep,
    actor: ActorDep,
    club_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ItemsOut[LeaderRowOut]:
    """One club's points table, or the caller's clubs combined."""
    svc = container.activities
    if club_id is not None:
        rows = await svc.leaderboard.top(actor, club_id, None, limit)
    else:
        rows = await svc.leaderboard.top_combined(actor, limit)
    return items(
        LeaderRowOut(rank=r.rank, display_name=r.display_name, points=r.points)
        for r in rows
    )


@router.get("/clubs/{club_id}/points/me")
async def my_points(
    club_id: UUID, container: ContainerDep, actor: ActorDep
) -> MyPointsOut:
    """The caller's points in a club."""
    return MyPointsOut.model_validate(
        await container.activities.leaderboard.my_points(actor, club_id)
    )


@router.put("/me/leaderboard-opt-out")
async def opt_out(
    body: OptOutIn, container: ContainerDep, actor: ActorDep
) -> OptOutOut:
    """Hide or show the caller on leaderboards."""
    await container.activities.leaderboard.set_opt_out(actor, body.opted_out)
    return OptOutOut(opted_out=body.opted_out)


@router.get("/clubs/{club_id}/attendance")
async def attendance(
    club_id: UUID, container: ContainerDep, actor: ActorDep
) -> ItemsOut[AttendanceRow]:
    """Attendance of a club."""
    rows = await container.activities.leaderboard.attendance(actor, club_id)
    return items(AttendanceRow.model_validate(r) for r in rows)


@router.put("/clubs/{club_id}/profile")
async def save_profile(
    club_id: UUID, body: ProfileIn, container: ContainerDep, actor: ActorDep
) -> ClubProfile:
    """Save the caller's answers to the club form."""
    return await container.activities.forms.save_profile(actor, club_id, body.answers)


@router.get("/clubs/{club_id}/profile")
async def my_profile(
    club_id: UUID, container: ContainerDep, actor: ActorDep
) -> ClubProfile | None:
    """The caller's answers to the club form."""
    return await container.activities.forms.my_profile(actor, club_id)


@router.get("/clubs/{club_id}/form-fields")
async def get_form_fields(
    club_id: UUID, container: ContainerDep, actor: ActorDep
) -> FormFieldsOut:
    """The club's form questions."""
    return FormFieldsOut(
        fields=await container.activities.forms.get_fields(actor, club_id)
    )


@router.put("/clubs/{club_id}/form-fields")
async def put_form_fields(
    club_id: UUID, body: FormFieldsIn, container: ContainerDep, actor: ActorDep
) -> FormFieldsOut:
    """Replace the club's form questions."""
    fields = await container.activities.forms.set_fields(
        actor, club_id, [f.model_dump() for f in body.fields]
    )
    return FormFieldsOut(fields=fields)


@router.get("/clubs/{club_id}/form-answers")
async def form_answers(
    club_id: UUID, container: ContainerDep, actor: ActorDep
) -> ItemsOut[MemberAnswersOut]:
    """Answers of every member (organizers)."""
    rows = await container.activities.forms.answers(actor, club_id)
    return items(
        MemberAnswersOut(
            user_id=prof.user_id,
            display_name=name,
            answers=prof.answers,
            updated_at=prof.updated_at,
        )
        for prof, name in rows
    )


@router.get("/clubs/{club_id}/points/rules")
async def get_points_rules(
    club_id: UUID, container: ContainerDep, actor: ActorDep
) -> PointsRulesOut:
    """Points per kind of activity."""
    return PointsRulesOut(
        rules=await container.activities.leaderboard.get_rules(actor, club_id)
    )


@router.put("/clubs/{club_id}/points/rules")
async def put_points_rules(
    club_id: UUID, body: PointsRulesIn, container: ContainerDep, actor: ActorDep
) -> PointsRulesOut:
    """Replace the club's point values."""
    return PointsRulesOut(
        rules=await container.activities.leaderboard.set_rules(
            actor, club_id, body.rules
        )
    )


@router.post("/clubs/{club_id}/points/awards", status_code=status.HTTP_201_CREATED)
async def award_points(
    club_id: UUID, body: AwardIn, container: ContainerDep, actor: ActorDep
) -> AwardOut:
    """Credit or deduct points by hand."""
    e = await container.activities.leaderboard.award_manual(
        actor, club_id, body.user_id, body.points, body.reason
    )
    return AwardOut(user_id=e.user_id, points=e.points, reason=e.reason)


@router.post("/events/{event_id}/draft-rounds", status_code=status.HTTP_201_CREATED)
async def open_round(
    event_id: UUID, body: RoundIn, container: ContainerDep, actor: ActorDep
) -> DraftRound:
    """Open drafting for an event."""
    return await container.activities.drafts.open_round(
        actor, event_id, body.club_id, body.needed
    )


@router.get("/clubs/{club_id}/draft-rounds")
async def list_rounds(
    club_id: UUID, container: ContainerDep, actor: ActorDep
) -> ItemsOut[DraftRound]:
    """Calls for volunteers of a club."""
    return items(await container.activities.drafts.list_rounds(actor, club_id))


@router.get("/draft-rounds/{round_id}/signups")
async def list_signups(
    round_id: UUID, container: ContainerDep, actor: ActorDep
) -> ItemsOut[DraftSignup]:
    """Who offered to help (organizers)."""
    return items(await container.activities.drafts.list_signups(actor, round_id))


@router.post("/draft-rounds/{round_id}/signups", status_code=status.HTTP_201_CREATED)
async def signup(
    round_id: UUID, body: SignupIn, container: ContainerDep, actor: ActorDep
) -> DraftSignup:
    """Sign up for a role."""
    return await container.activities.drafts.signup(
        actor, round_id, body.role, body.answers
    )


@router.get("/draft-rounds/{round_id}/ranking")
async def ranking(
    round_id: UUID, container: ContainerDep, actor: ActorDep
) -> ItemsOut[Ranked]:
    """Candidates ranked by past performance."""
    return items(await container.activities.drafts.rank(actor, round_id))


@router.post("/draft-rounds/{round_id}/picks", status_code=status.HTTP_201_CREATED)
async def pick(
    round_id: UUID, body: PickIn, container: ContainerDep, actor: ActorDep
) -> DraftPick:
    """Pick a person for a role."""
    return await container.activities.drafts.pick(
        actor, round_id, body.user_id, body.role
    )


@router.post("/picks/{pick_id}:invite")
async def invite(pick_id: UUID, container: ContainerDep, actor: ActorDep) -> DraftPick:
    """Invite the picked person."""
    return await container.activities.drafts.invite(actor, pick_id)


@router.post("/picks/{pick_id}:respond")
async def respond(
    pick_id: UUID, body: RespondIn, container: ContainerDep, actor: ActorDep
) -> DraftPick:
    """The picked person answers."""
    return await container.activities.drafts.respond(actor, pick_id, body.accept)


@router.post("/picks/{pick_id}:complete")
async def complete(
    pick_id: UUID, container: ContainerDep, actor: ActorDep
) -> DraftPick:
    """Mark the role as done (awards points)."""
    return await container.activities.drafts.complete(actor, pick_id)


@router.get("/opportunities")
async def list_opportunities(
    container: ContainerDep, actor: ActorDep
) -> OpportunityListOut:
    """Opportunities shown on my.iht."""
    rows = await container.activities.opportunities.list(actor, SURFACE)
    return OpportunityListOut(items=[OpportunityOut.of(e) for e in rows])


@router.get("/opportunities/{opportunity_id}")
async def get_opportunity(
    opportunity_id: UUID, container: ContainerDep, actor: ActorDep
) -> OpportunityOut:
    """One opportunity; hidden ones answer 404."""
    entry = await container.activities.opportunities.get(actor, opportunity_id, SURFACE)
    return OpportunityOut.of(entry)
