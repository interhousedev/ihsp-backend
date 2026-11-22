"""Project ideas and the helpers a student may contact (`/v1/admission/projects`)."""

from typing import Annotated
from uuid import UUID

from app.interfaces.http.v1.admission.deps import AdmissionCtx, ContainerDep
from app.interfaces.http.v1.admission.routes_items import LocaleHeader, _locale
from app.interfaces.http.v1.admission.schemas_projects import (
    BriefIn,
    HelperListOut,
    HelperOut,
    ProjectIdeasOut,
    ProjectRunOut,
)

from fastapi import APIRouter, Query, status

router = APIRouter(prefix="/v1/admission", tags=["admission"])


async def create_project_ideas(
    body: BriefIn,
    container: ContainerDep,
    ctx: AdmissionCtx,
    accept_language: LocaleHeader = None,
) -> ProjectRunOut:
    """Suggest projects for the brief (counts against the weekly AI limit)."""
    run = await container.admission.project_ideas.generate(
        ctx, body.model_dump(), _locale(accept_language)
    )
    return ProjectRunOut.of(run)


async def list_project_ideas(
    container: ContainerDep, ctx: AdmissionCtx
) -> ProjectIdeasOut:
    """The newest run and the few before it."""
    return ProjectIdeasOut.of(await container.admission.project_ideas.overview(ctx))


async def get_project_run(
    run_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> ProjectRunOut:
    """One of the caller's own runs."""
    return ProjectRunOut.of(await container.admission.project_ideas.get(ctx, run_id))


async def list_project_helpers(
    container: ContainerDep,
    ctx: AdmissionCtx,
    tag: Annotated[list[str] | None, Query(max_length=6)] = None,
) -> HelperListOut:
    """Active helpers that share a tag, best match first."""
    found = await container.admission.project_helpers.for_tags(tag or [])
    return HelperListOut(items=[HelperOut.of(h) for h in found])


_R = router.add_api_route
_R(
    "/projects/ideas",
    create_project_ideas,
    methods=["POST"],
    response_model=ProjectRunOut,
    status_code=status.HTTP_201_CREATED,
    operation_id="admission_project_ideas_create",
)
_R(
    "/projects/ideas",
    list_project_ideas,
    methods=["GET"],
    response_model=ProjectIdeasOut,
    operation_id="admission_project_ideas_list",
)
_R(
    "/projects/ideas/{run_id}",
    get_project_run,
    methods=["GET"],
    response_model=ProjectRunOut,
    operation_id="admission_project_ideas_get",
)
_R(
    "/projects/helpers",
    list_project_helpers,
    methods=["GET"],
    response_model=HelperListOut,
    operation_id="admission_project_helpers_list",
)
