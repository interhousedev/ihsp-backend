"""The Today feed (`/v1/admission/today`, `/v1/admission/me/season`)."""

import datetime as dt
from typing import Annotated, Literal
from uuid import UUID

from app.interfaces.http.v1.admission.deps import ContainerDep, StudentCtx
from app.interfaces.http.v1.admission.routes_items import _locale
from app.modules.admission.application.today import TodayView
from app.modules.admission.domain.today import MAX_DEADLINES, MAX_NEXT, NodeState

from fastapi import APIRouter, Header, Response
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/admission", tags=["admission"])

SeasonKeyOut = Literal["explore", "build", "choose", "write", "submit", "results"]


class ChecklistLineOut(BaseModel):
    """One line of the season checklist."""

    key: str
    label: str
    done: bool
    progress: str | None
    href: str


class SeasonOut(BaseModel):
    """The season in force; `source` says whether the student fixed it."""

    key: SeasonKeyOut
    source: Literal["auto", "override"]
    checklist: list[ChecklistLineOut]


class NextActionOut(BaseModel):
    """A ranked next step."""

    key: str
    title: str
    why: str
    minutes: int
    href: str
    list_entry_id: str | None
    kind: str
    pinned_by: str | None = Field(
        default=None, description="Name of the counselor who pinned it (`pinned`)."
    )


class StreakOut(BaseModel):
    """Consecutive active days; `last7` runs oldest to today."""

    days: int
    today_done: bool
    last7: list[bool] = Field(min_length=7, max_length=7)


class TodayReadinessOut(BaseModel):
    """The readiness percentage."""

    percent: int = Field(ge=0, le=100)


class TodayDeadlineOut(BaseModel):
    """An upcoming deadline."""

    date: dt.date
    title: str
    list_entry_id: UUID | None
    kind: str
    href: str


class RoadmapNodeOut(BaseModel):
    """A stop of the roadmap; the web names `key` in the student's language."""

    key: str
    state: NodeState
    href: str
    progress: str | None = None


class ProgramOut(BaseModel):
    """A newly published program matching the student's fields."""

    id: UUID
    title: str
    kind: str
    provider: str | None
    href: str


class NewProgramsOut(BaseModel):
    """Programs published since the student last opened the block."""

    unseen: int = Field(ge=0)
    items: list[ProgramOut]


class TodayOut(BaseModel):
    """What the Today screen shows."""

    season: SeasonOut
    next: list[NextActionOut] = Field(max_length=MAX_NEXT)
    streak: StreakOut
    readiness: TodayReadinessOut
    deadlines: list[TodayDeadlineOut] = Field(max_length=MAX_DEADLINES)
    roadmap: list[RoadmapNodeOut] = Field(default_factory=list)
    programs: NewProgramsOut = Field(
        default_factory=lambda: NewProgramsOut(unseen=0, items=[])
    )

    @classmethod
    def of(cls, v: TodayView) -> "TodayOut":
        """Map the application result."""
        return cls(
            season=SeasonOut(
                key=v.season.key,
                source="override" if v.season.source == "override" else "auto",
                checklist=[
                    ChecklistLineOut(
                        key=c.key,
                        label=c.label,
                        done=c.done,
                        progress=c.progress,
                        href=c.href,
                    )
                    for c in v.season.checklist
                ],
            ),
            next=[
                NextActionOut(
                    key=n.key,
                    title=n.title,
                    why=n.why,
                    minutes=n.minutes,
                    href=n.href,
                    list_entry_id=n.list_entry_id,
                    kind=n.kind,
                    pinned_by=n.pinned_by,
                )
                for n in v.next
            ],
            streak=StreakOut(
                days=v.streak_days, today_done=v.today_done, last7=list(v.last7)
            ),
            readiness=TodayReadinessOut(percent=v.readiness_percent),
            roadmap=[
                RoadmapNodeOut(
                    key=n.key, state=n.state, href=n.href, progress=n.progress
                )
                for n in v.roadmap
            ],
            programs=NewProgramsOut(
                unseen=v.programs.unseen,
                items=[
                    ProgramOut(
                        id=p.id,
                        title=p.title,
                        kind=p.kind,
                        provider=p.provider,
                        href=p.href,
                    )
                    for p in v.programs.items
                ],
            ),
            deadlines=[
                TodayDeadlineOut(
                    date=d.date,
                    title=d.title,
                    list_entry_id=d.list_entry_id,
                    kind=d.kind,
                    href=d.href,
                )
                for d in v.deadlines
            ],
        )


class SeasonIn(BaseModel):
    """The season to fix; null goes back to the automatic one."""

    key: SeasonKeyOut | None


async def get_today(
    container: ContainerDep,
    ctx: StudentCtx,
    accept_language: Annotated[str | None, Header()] = None,
) -> TodayOut:
    """My season, next steps, streak, readiness and nearest deadlines."""
    view = await container.admission.today.get(ctx, _locale(accept_language))
    return TodayOut.of(view)


async def put_season(
    body: SeasonIn,
    container: ContainerDep,
    ctx: StudentCtx,
    accept_language: Annotated[str | None, Header()] = None,
) -> TodayOut:
    """Fix the season (or null for automatic); returns the refreshed feed."""
    await container.admission.today.set_season(ctx, body.key)
    view = await container.admission.today.get(ctx, _locale(accept_language))
    return TodayOut.of(view)


router.add_api_route(
    "/today",
    get_today,
    methods=["GET"],
    response_model=TodayOut,
    operation_id="admission_today",
)
router.add_api_route(
    "/me/season",
    put_season,
    methods=["PUT"],
    response_model=TodayOut,
    operation_id="admission_set_season",
)


class SnoozeIn(BaseModel):
    """The next action to hide for three days (twice at most when dated)."""

    key: str = Field(min_length=1, max_length=200)


async def post_snooze(
    body: SnoozeIn, container: ContainerDep, ctx: StudentCtx
) -> Response:
    """Hide a next action from `/today` for three days."""
    await container.admission.today.snooze(ctx, body.key)
    return Response(status_code=204)


router.add_api_route(
    "/today/snooze",
    post_snooze,
    methods=["POST"],
    status_code=204,
    response_class=Response,
    operation_id="admission_snooze_today",
)


async def post_programs_seen(container: ContainerDep, ctx: StudentCtx) -> Response:
    """Mark the new programs as seen; the unseen count restarts from zero."""
    await container.admission.today.mark_programs_seen(ctx)
    return Response(status_code=204)


router.add_api_route(
    "/today/programs/seen",
    post_programs_seen,
    methods=["POST"],
    status_code=204,
    response_class=Response,
    operation_id="admission_programs_seen",
)
