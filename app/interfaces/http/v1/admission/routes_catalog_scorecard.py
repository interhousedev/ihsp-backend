"""College Scorecard lookup and attach (`/v1/admission/staff/catalog/*`)."""

from typing import Annotated
from uuid import UUID

from app.interfaces.http.v1.admission.deps import AnyContext, ContainerDep
from app.interfaces.http.v1.admission.schemas_scorecard import (
    ScorecardAttachIn,
    ScorecardSchoolOut,
    ScorecardSearchOut,
)
from app.modules.admission.domain.catalog_staff import QUERY_MAX

from fastapi import APIRouter, Query

router = APIRouter(prefix="/v1/admission", tags=["admission"])


async def search_scorecard(
    container: ContainerDep,
    ctx: AnyContext,
    q: Annotated[str, Query(min_length=1, max_length=QUERY_MAX)],
) -> ScorecardSearchOut:
    """Candidates by school name or numeric UNITID (curators)."""
    found = await container.admission.catalog_scorecard.search(ctx, q)
    return ScorecardSearchOut(items=[ScorecardSchoolOut.of(s) for s in found])


async def attach_scorecard(
    institution_id: UUID,
    body: ScorecardAttachIn,
    container: ContainerDep,
    ctx: AnyContext,
) -> ScorecardSchoolOut:
    """Upsert the school's sourced facts into a US institution (curators)."""
    school = await container.admission.catalog_scorecard.attach(
        ctx, institution_id, body.unitid
    )
    return ScorecardSchoolOut.of(school)


router.add_api_route(
    "/staff/catalog/scorecard/search",
    search_scorecard,
    methods=["GET"],
    response_model=ScorecardSearchOut,
    operation_id="admission_staff_scorecard_search",
)
router.add_api_route(
    "/staff/catalog/institutions/{institution_id}/scorecard",
    attach_scorecard,
    methods=["POST"],
    response_model=ScorecardSchoolOut,
    operation_id="admission_staff_scorecard_attach",
)
