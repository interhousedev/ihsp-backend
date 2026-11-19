"""Opportunities catalog, moderation and student plans.

Routes: `/v1/admission/opportunities/*`, `/v1/admission/staff/opportunities/*`.
"""

import datetime as dt
from typing import Annotated, Literal, cast
from uuid import UUID

from app.interfaces.http.v1.admission.deps import AdmissionCtx, AnyContext, ContainerDep
from app.interfaces.http.v1.admission.schemas_opp_comments import OppCommentOut
from app.interfaces.http.v1.admission.schemas_opportunities import (
    AiPlanEnvelope,
    AiPlanIn,
    AiPlanOut,
    ArchiveIn,
    AwardType,
    CollegeCredit,
    DeadlineListOut,
    DeadlineOut,
    Kind,
    OpportunityDetailOut,
    OpportunityListOut,
    OpportunityOut,
    PlanEntryIn,
    PlanEntryOut,
    PlanOut,
    ReviewIn,
    Scope,
    Sort,
    SubmissionIn,
    SubmissionListOut,
    SubmissionOut,
    TaxonomyFieldOut,
    TaxonomyNodeIn,
    TaxonomyNodeOut,
    TaxonomyOut,
)
from app.modules.admission.application.opportunities import CatalogFilter

from fastapi import APIRouter, Query, Response, status

router = APIRouter(prefix="/v1/admission", tags=["admission"])


async def get_opportunity_taxonomy(
    container: ContainerDep, ctx: AnyContext
) -> TaxonomyOut:
    """Fields, subfields and subjects."""
    svc = container.admission.opportunities
    tree = await svc.taxonomy()
    return TaxonomyOut(
        fields=[TaxonomyFieldOut.of(f) for f in tree],
        can_moderate=svc.can_moderate(ctx),
    )


async def create_taxonomy_node(
    body: TaxonomyNodeIn, container: ContainerDep, ctx: AnyContext
) -> TaxonomyNodeOut:
    """Add a field, subfield or subject (administrators)."""
    node = await container.admission.opportunities.save_node(
        ctx,
        node_id=None,
        level=body.level,
        parent_id=body.parent_id,
        names=body.names,
        position=body.position,
    )
    return TaxonomyNodeOut.of(node)


async def update_taxonomy_node(
    node_id: UUID, body: TaxonomyNodeIn, container: ContainerDep, ctx: AnyContext
) -> TaxonomyNodeOut:
    """Rename or move a node (the level must match the stored one)."""
    node = await container.admission.opportunities.save_node(
        ctx,
        node_id=node_id,
        level=body.level,
        parent_id=body.parent_id,
        names=body.names,
        position=body.position,
    )
    return TaxonomyNodeOut.of(node)


async def delete_taxonomy_node(
    node_id: UUID, container: ContainerDep, ctx: AnyContext
) -> Response:
    """Delete an unused node."""
    await container.admission.opportunities.delete_node(ctx, node_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def list_opportunities(
    container: ContainerDep,
    ctx: AnyContext,
    field_id: UUID | None = None,
    subfield_id: UUID | None = None,
    subject_id: UUID | None = None,
    kind: Kind | None = None,
    grade: Annotated[int | None, Query(ge=9, le=12)] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    country: Annotated[str | None, Query(max_length=300)] = None,
    online: bool | None = None,
    free: bool | None = None,
    max_tuition: Annotated[int | None, Query(ge=0)] = None,
    award_type: AwardType | None = None,
    scope: Scope | None = None,
    org_id: UUID | None = None,
    college_credit: CollegeCredit | None = None,
    sort: Sort | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=200)] = 200,
) -> OpportunityListOut:
    """One page of published entries matching the filters."""
    svc = container.admission.opportunities
    found = await svc.catalog(
        CatalogFilter(
            field_id=field_id,
            subfield_id=subfield_id,
            subject_id=subject_id,
            kind=kind,
            grade=grade,
            query=q,
            country=country,
            online=online,
            free=free,
            max_tuition=max_tuition,
            award_type=award_type,
            scope=scope,
            org_id=org_id,
            college_credit=college_credit,
            sort=sort,
            page=page,
            size=size,
        ),
        ctx,
    )
    orgs = await container.admission.orgs.by_ids(
        [o.draft.org_id for o in found.items if o.draft.org_id]
    )
    counts = await container.admission.opportunity_comments.counts(
        [o.id for o in found.items]
    )
    return OpportunityListOut(
        items=[
            OpportunityOut.of(
                o,
                svc.upcoming(o),
                orgs.get(o.draft.org_id) if o.draft.org_id else None,
                counts.get(o.id, 0),
                o.id in found.for_you,
            )
            for o in found.items
        ],
        total=found.total,
        page=found.page,
        size=found.size,
        sort=cast(Sort, found.sort),
    )


async def get_opportunity(
    opportunity_id: UUID, container: ContainerDep, ctx: AnyContext
) -> OpportunityDetailOut:
    """One published entry with its next dates, organization and comments."""
    svc = container.admission.opportunities
    o = await svc.get(opportunity_id)
    org = None
    if o.draft.org_id:
        org = (await container.admission.orgs.by_ids([o.draft.org_id])).get(
            o.draft.org_id
        )
    comments = await container.admission.opportunity_comments.list(ctx, o.id)
    base = OpportunityOut.of(o, svc.upcoming(o), org, 0)
    return OpportunityDetailOut(
        **base.model_dump(exclude={"comment_count", "org"}),
        org=base.org,
        comment_count=sum(1 for c in comments if c.comment.status == "published"),
        comments=[OppCommentOut.of(c) for c in comments],
        can_moderate=svc.can_moderate(ctx),
    )


async def submit_opportunity(
    body: SubmissionIn, container: ContainerDep, ctx: AnyContext
) -> SubmissionOut:
    """Propose a new entry or an edit; it waits for moderation."""
    sub = await container.admission.opportunities.submit(
        ctx, body.fields.draft(body.note), target_id=body.target_id
    )
    return SubmissionOut.of(sub)


async def list_opportunity_submissions(
    container: ContainerDep,
    ctx: AnyContext,
    submission_status: Annotated[
        Literal["pending", "approved", "rejected"] | None, Query(alias="status")
    ] = None,
) -> SubmissionListOut:
    """Every submission for a moderator, the caller's own otherwise."""
    svc = container.admission.opportunities
    items = await svc.submissions(ctx, status=submission_status)
    return SubmissionListOut(
        items=[SubmissionOut.of(s) for s in items],
        can_moderate=svc.can_moderate(ctx),
    )


async def review_opportunity_submission(
    submission_id: UUID, body: ReviewIn, container: ContainerDep, ctx: AnyContext
) -> SubmissionOut:
    """Approve (publishing it) or reject with a reason."""
    sub = await container.admission.opportunities.review(
        ctx,
        submission_id,
        approve=body.approve,
        reason=body.reason,
        lock_version=body.lock_version,
    )
    return SubmissionOut.of(sub)


async def archive_opportunity(
    opportunity_id: UUID, body: ArchiveIn, container: ContainerDep, ctx: AnyContext
) -> Response:
    """Hide or restore a published entry."""
    await container.admission.opportunities.set_archived(
        ctx, opportunity_id, body.archived
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def get_my_opportunity_plan(
    container: ContainerDep, ctx: AdmissionCtx
) -> PlanOut:
    """The caller's saved entries with analytics."""
    view = await container.admission.opportunities.plan_of(ctx, ctx.user_id)
    return PlanOut.of(view)


async def get_student_opportunity_plan(
    student_id: UUID, container: ContainerDep, ctx: AnyContext
) -> PlanOut:
    """A student's plan for assigned staff."""
    view = await container.admission.opportunities.plan_of(ctx, student_id)
    return PlanOut.of(view)


async def save_opportunity_to_plan(
    opportunity_id: UUID, body: PlanEntryIn, container: ContainerDep, ctx: AdmissionCtx
) -> PlanEntryOut:
    """Save (or re-place) an entry in the caller's plan."""
    entry = await container.admission.opportunities.save_to_plan(
        ctx, opportunity_id, planned_grade=body.planned_grade, note=body.note
    )
    return PlanEntryOut.of(entry)


async def remove_opportunity_from_plan(
    opportunity_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> Response:
    """Drop an entry from the caller's plan."""
    await container.admission.opportunities.remove_from_plan(ctx, opportunity_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def list_opportunity_deadlines(
    container: ContainerDep,
    ctx: AdmissionCtx,
    start: dt.date,
    end: dt.date,
) -> DeadlineListOut:
    """Dated events of the caller's saved entries in [start, end] (≤ 2 years)."""
    end = min(end, start + dt.timedelta(days=731))
    items = await container.admission.opportunities.deadlines_for(
        ctx.user_id, start, end
    )
    return DeadlineListOut(items=[DeadlineOut.of(d) for d in items])


async def get_opportunity_ai_plan(
    container: ContainerDep, ctx: AdmissionCtx
) -> AiPlanEnvelope:
    """The last generated grade 9–12 plan."""
    plan = await container.admission.opportunity_planner.last(ctx)
    return AiPlanEnvelope(plan=AiPlanOut.of(plan) if plan else None)


async def generate_opportunity_ai_plan(
    body: AiPlanIn, container: ContainerDep, ctx: AdmissionCtx
) -> AiPlanOut:
    """Build a grade 9–12 plan from the saved entries (needs `admission_ai`)."""
    plan = await container.admission.opportunity_planner.generate(
        ctx, body.locale, interests=body.interests, career=body.career
    )
    return AiPlanOut.of(plan)


_R = router.add_api_route
_NO = status.HTTP_204_NO_CONTENT
_R(
    "/opportunities/taxonomy",
    get_opportunity_taxonomy,
    methods=["GET"],
    response_model=TaxonomyOut,
    operation_id="admission_get_opportunity_taxonomy",
)
_R(
    "/staff/opportunities/taxonomy",
    create_taxonomy_node,
    methods=["POST"],
    status_code=status.HTTP_201_CREATED,
    response_model=TaxonomyNodeOut,
    operation_id="admission_create_opportunity_taxonomy_node",
)
_R(
    "/staff/opportunities/taxonomy/{node_id}",
    update_taxonomy_node,
    methods=["PATCH"],
    response_model=TaxonomyNodeOut,
    operation_id="admission_update_opportunity_taxonomy_node",
)
_R(
    "/staff/opportunities/taxonomy/{node_id}",
    delete_taxonomy_node,
    methods=["DELETE"],
    status_code=_NO,
    response_class=Response,
    operation_id="admission_delete_opportunity_taxonomy_node",
)
# Literal paths before `/opportunities/{opportunity_id}`.
_R(
    "/opportunities/submissions",
    submit_opportunity,
    methods=["POST"],
    status_code=status.HTTP_201_CREATED,
    response_model=SubmissionOut,
    operation_id="admission_submit_opportunity",
)
_R(
    "/opportunities/submissions",
    list_opportunity_submissions,
    methods=["GET"],
    response_model=SubmissionListOut,
    operation_id="admission_list_opportunity_submissions",
)
_R(
    "/staff/opportunities/submissions/{submission_id}/review",
    review_opportunity_submission,
    methods=["POST"],
    response_model=SubmissionOut,
    operation_id="admission_review_opportunity_submission",
)
_R(
    "/staff/opportunities/{opportunity_id}/archive",
    archive_opportunity,
    methods=["POST"],
    status_code=_NO,
    response_class=Response,
    operation_id="admission_archive_opportunity",
)
_R(
    "/opportunities/plan",
    get_my_opportunity_plan,
    methods=["GET"],
    response_model=PlanOut,
    operation_id="admission_get_my_opportunity_plan",
)
_R(
    "/opportunities/plan/deadlines",
    list_opportunity_deadlines,
    methods=["GET"],
    response_model=DeadlineListOut,
    operation_id="admission_list_opportunity_deadlines",
)
_R(
    "/opportunities/plan/ai",
    get_opportunity_ai_plan,
    methods=["GET"],
    response_model=AiPlanEnvelope,
    operation_id="admission_get_opportunity_ai_plan",
)
_R(
    "/opportunities/plan/ai",
    generate_opportunity_ai_plan,
    methods=["POST"],
    response_model=AiPlanOut,
    operation_id="admission_generate_opportunity_ai_plan",
)
_R(
    "/opportunities/plan/{opportunity_id}",
    save_opportunity_to_plan,
    methods=["PUT"],
    response_model=PlanEntryOut,
    operation_id="admission_save_opportunity_to_plan",
)
_R(
    "/opportunities/plan/{opportunity_id}",
    remove_opportunity_from_plan,
    methods=["DELETE"],
    status_code=_NO,
    response_class=Response,
    operation_id="admission_remove_opportunity_from_plan",
)
_R(
    "/students/{student_id}/opportunities/plan",
    get_student_opportunity_plan,
    methods=["GET"],
    response_model=PlanOut,
    operation_id="admission_get_student_opportunity_plan",
)
_R(
    "/opportunities",
    list_opportunities,
    methods=["GET"],
    response_model=OpportunityListOut,
    operation_id="admission_list_opportunities",
)
_R(
    "/opportunities/{opportunity_id}",
    get_opportunity,
    methods=["GET"],
    response_model=OpportunityDetailOut,
    operation_id="admission_get_opportunity",
)
