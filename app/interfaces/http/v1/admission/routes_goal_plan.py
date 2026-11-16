"""Goal-plan milestone routes (`/v1/admission/goal-plan*`)."""

import datetime as dt
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from app.interfaces.http.v1.admission.deps import AdmissionCtx, ContainerDep
from app.interfaces.http.v1.admission.routes_items import _locale
from app.modules.admission.domain.goal_plan import (
    MAX_MILESTONES,
    TITLE_MAX,
    GoalMilestone,
)

from fastapi import APIRouter, Header, Response, status
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(prefix="/v1/admission", tags=["admission"])


class MilestoneIn(BaseModel):
    """A new milestone; `due_month` is stored as the first day of its month."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(max_length=TITLE_MAX)
    item_id: UUID | None = None
    due_month: dt.date | None = None
    target_value: Decimal | None = None
    status: Literal["planned", "done", "dropped"] = "planned"


class MilestonePutIn(MilestoneIn):
    """A milestone of the replacing plan; a known `id` keeps the stored one."""

    id: UUID | None = None


class GoalPlanPutIn(BaseModel):
    """The whole plan in display order (at most 12)."""

    model_config = ConfigDict(extra="forbid")

    items: list[MilestonePutIn] = Field(max_length=MAX_MILESTONES)


class SuggestionOut(BaseModel):
    """A proposed milestone; save it with POST or PUT."""

    title: str
    item_id: UUID | None
    due_month: dt.date


class SuggestionsOut(BaseModel):
    """Proposals from the model; nothing is stored."""

    items: list[SuggestionOut]


class MilestonePatchIn(BaseModel):
    """Changed fields; `lock_version` is the one the client read."""

    model_config = ConfigDict(extra="forbid")

    lock_version: int
    title: str | None = Field(default=None, max_length=TITLE_MAX)
    item_id: UUID | None = None
    due_month: dt.date | None = None
    target_value: Decimal | None = None
    status: Literal["planned", "done", "dropped"] | None = None
    sort_order: int | None = Field(default=None, ge=0, le=MAX_MILESTONES)


class MilestoneOut(BaseModel):
    """A stored milestone."""

    id: UUID
    student_id: UUID
    item_id: UUID | None
    title: str
    due_month: dt.date | None
    target_value: Decimal | None
    status: str
    done_at: dt.datetime | None
    source: str
    sort_order: int
    lock_version: int

    @classmethod
    def of(cls, m: GoalMilestone) -> "MilestoneOut":
        """Map the milestone."""
        return cls(
            id=m.id,
            student_id=m.student_id,
            item_id=m.item_id,
            title=m.title,
            due_month=m.due_month,
            target_value=m.target_value,
            status=m.status,
            done_at=m.done_at,
            source=m.source,
            sort_order=m.sort_order,
            lock_version=m.lock_version,
        )


class GoalPlanOut(BaseModel):
    """The milestones in display order."""

    items: list[MilestoneOut]
    next_cursor: str | None = None


async def get_goal_plan(container: ContainerDep, ctx: AdmissionCtx) -> GoalPlanOut:
    """My milestones."""
    rows = await container.admission.goal_plan.list(ctx, ctx.user_id)
    return GoalPlanOut(items=[MilestoneOut.of(m) for m in rows])


async def get_student_goal_plan(
    student_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> GoalPlanOut:
    """A student's milestones (staff in scope or the student)."""
    rows = await container.admission.goal_plan.list(ctx, student_id)
    return GoalPlanOut(items=[MilestoneOut.of(m) for m in rows])


async def create_milestone(
    body: MilestoneIn, container: ContainerDep, ctx: AdmissionCtx
) -> MilestoneOut:
    """Add a milestone to my plan (at most 12)."""
    draft = GoalMilestone(id=UUID(int=0), student_id=ctx.user_id, **body.model_dump())
    return MilestoneOut.of(await container.admission.goal_plan.create(ctx, draft))


async def patch_milestone(
    milestone_id: UUID,
    body: MilestonePatchIn,
    container: ContainerDep,
    ctx: AdmissionCtx,
) -> MilestoneOut:
    """Change fields of my milestone."""
    changes = body.model_dump(exclude_unset=True, exclude={"lock_version"})
    for key in ("title", "status", "sort_order"):
        if key in changes and changes[key] is None:
            del changes[key]
    stored = await container.admission.goal_plan.update(
        ctx, milestone_id, changes, body.lock_version
    )
    return MilestoneOut.of(stored)


async def delete_milestone(
    milestone_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> Response:
    """Delete my milestone."""
    await container.admission.goal_plan.delete(ctx, milestone_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


router.add_api_route(
    "/goal-plan",
    get_goal_plan,
    methods=["GET"],
    response_model=GoalPlanOut,
    operation_id="admission_get_goal_plan",
)
router.add_api_route(
    "/students/{student_id}/goal-plan",
    get_student_goal_plan,
    methods=["GET"],
    response_model=GoalPlanOut,
    operation_id="admission_get_student_goal_plan",
)


async def put_goal_plan(
    body: GoalPlanPutIn, container: ContainerDep, ctx: AdmissionCtx
) -> GoalPlanOut:
    """Replace my whole plan (at most 12 milestones)."""
    drafts = [
        GoalMilestone(
            id=m.id or UUID(int=0),
            student_id=ctx.user_id,
            **m.model_dump(exclude={"id"}),
        )
        for m in body.items
    ]
    rows = await container.admission.goal_plan.replace(ctx, drafts)
    return GoalPlanOut(items=[MilestoneOut.of(m) for m in rows])


async def suggest_goal_plan(
    container: ContainerDep,
    ctx: AdmissionCtx,
    accept_language: Annotated[str | None, Header(alias="Accept-Language")] = None,
) -> SuggestionsOut:
    """Propose next steps with AI (consent and a weekly limit apply)."""
    found = await container.admission.goal_plan_suggest.suggest(
        ctx, _locale(accept_language)
    )
    return SuggestionsOut(
        items=[
            SuggestionOut(title=s.title, item_id=s.item_id, due_month=s.due_month)
            for s in found
        ]
    )


router.add_api_route(
    "/goal-plan",
    put_goal_plan,
    methods=["PUT"],
    response_model=GoalPlanOut,
    operation_id="admission_put_goal_plan",
)
router.add_api_route(
    "/goal-plan/suggest",
    suggest_goal_plan,
    methods=["POST"],
    response_model=SuggestionsOut,
    operation_id="admission_suggest_goal_plan",
)
router.add_api_route(
    "/goal-plan/milestones",
    create_milestone,
    methods=["POST"],
    status_code=status.HTTP_201_CREATED,
    response_model=MilestoneOut,
    operation_id="admission_create_milestone",
)
router.add_api_route(
    "/goal-plan/milestones/{milestone_id}",
    patch_milestone,
    methods=["PATCH"],
    response_model=MilestoneOut,
    operation_id="admission_patch_milestone",
)
router.add_api_route(
    "/goal-plan/milestones/{milestone_id}",
    delete_milestone,
    methods=["DELETE"],
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="admission_delete_milestone",
)
