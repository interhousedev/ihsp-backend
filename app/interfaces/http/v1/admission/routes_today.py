"""The Today feed (`/v1/admission/today`, `/v1/admission/me/season`)."""

import datetime as dt
from typing import Annotated, Literal
from uuid import UUID

from app.interfaces.http.v1.admission.deps import ContainerDep, StudentCtx
from app.interfaces.http.v1.admission.routes_items import _locale
from app.modules.admission.application.today import TodayView
from app.modules.admission.domain.today import MAX_DEADLINES, MAX_NEXT

from fastapi import APIRouter, Header
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


class TodayOut(BaseModel):
    """What the Today screen shows."""

    season: SeasonOut
    next: list[NextActionOut] = Field(max_length=MAX_NEXT)
    streak: StreakOut
    readiness: TodayReadinessOut
    deadlines: list[TodayDeadlineOut] = Field(max_length=MAX_DEADLINES)

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
                )
                for n in v.next
            ],
            streak=StreakOut(
                days=v.streak_days, today_done=v.today_done, last7=list(v.last7)
            ),
            readiness=TodayReadinessOut(percent=v.readiness_percent),
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
