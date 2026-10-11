"""Routes /v1/admin/ai: limits, extensions and the usage report (admin only)."""

from datetime import date
from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.interfaces.http.v1.admin_ai.schemas import (
    ExtensionBody,
    ExtensionOut,
    ExtensionsResponse,
    GroupBy,
    LimitsBody,
    LimitsResponse,
    StudentOut,
    StudentsResponse,
    UsageResponse,
)
from app.shared.actor import Actor, Role

from fastapi import APIRouter, Depends, Query, Response, status

router = APIRouter(prefix="/v1/admin/ai", tags=["admin-ai"])

ContainerDep = Annotated[Container, Depends(get_container)]
AdminActor = Annotated[Actor, Depends(require_roles(Role.ADMIN))]


@router.get("/limits", response_model=LimitsResponse)
async def get_limits(container: ContainerDep, actor: AdminActor) -> LimitsResponse:
    """Every editable AI limit with its value and environment default."""
    rows = await container.admin.limit_admin.catalogue(actor)
    return LimitsResponse.of(rows)


@router.put("/limits", response_model=LimitsResponse)
async def put_limits(
    body: LimitsBody, container: ContainerDep, actor: AdminActor
) -> LimitsResponse:
    """Change some limits; null resets a limit to its environment value."""
    rows = await container.admin.limit_admin.update(actor, body.limits)
    return LimitsResponse.of(rows)


@router.get("/usage", response_model=UsageResponse, response_model_by_alias=True)
async def get_usage(
    container: ContainerDep,
    actor: AdminActor,
    from_day: Annotated[date | None, Query(alias="from")] = None,
    to_day: Annotated[date | None, Query(alias="to")] = None,
    group_by: GroupBy = "day",
) -> UsageResponse:
    """Tokens, calls and cost of a date range, grouped (Tashkent dates)."""
    view = await container.ai.usage_report.execute(
        actor, from_day=from_day, to_day=to_day, group_by=group_by
    )
    return UsageResponse.of(view)


@router.get("/limit-extensions", response_model=ExtensionsResponse)
async def list_extensions(
    container: ContainerDep,
    actor: AdminActor,
    user_id: Annotated[UUID | None, Query()] = None,
) -> ExtensionsResponse:
    """Every extension, or only the one of a student."""
    rows = await container.admin.limit_admin.extensions(actor, user_id=user_id)
    return ExtensionsResponse(items=[ExtensionOut.of(row) for row in rows])


@router.get("/limit-extensions/students", response_model=StudentsResponse)
async def search_students(
    container: ContainerDep,
    actor: AdminActor,
    q: Annotated[str, Query(min_length=2, max_length=100)],
) -> StudentsResponse:
    """Students whose name or login matches (up to 20)."""
    users = await container.admin.limit_admin.search_students(actor, q.strip())
    return StudentsResponse(items=[StudentOut.of(user) for user in users])


@router.put("/limit-extensions/{user_id}", response_model=ExtensionOut)
async def put_extension(
    user_id: UUID, body: ExtensionBody, container: ContainerDep, actor: AdminActor
) -> ExtensionOut:
    """Create or replace a student's extension (multiplier or values, to a date)."""
    row = await container.admin.limit_admin.save_extension(actor, user_id, body.terms())
    return ExtensionOut.of(row)


@router.delete(
    "/limit-extensions/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_extension(
    user_id: UUID, container: ContainerDep, actor: AdminActor
) -> Response:
    """Remove the extension of a student."""
    await container.admin.limit_admin.delete_extension(actor, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
