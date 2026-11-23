"""Educational trajectories: browsing, progress and the curator editor."""

from typing import Annotated
from uuid import UUID

from app.interfaces.http.v1.admission.deps import (
    AdmissionCtx,
    AnyContext,
    ContainerDep,
    StudentCtx,
)
from app.interfaces.http.v1.admission.schemas_trajectories import (
    NodeProgressIn,
    ResourceHitListOut,
    ResourceHitOut,
    TrajectoryDetailOut,
    TrajectoryIn,
    TrajectoryListOut,
    TrajectoryOut,
    TrajectoryStaffListOut,
    TrajectorySummaryOut,
)
from app.modules.admission.application.trajectories import TrajectorySummary
from app.modules.admission.domain.trajectories import (
    ResourceKind,
    required_ids,
)

from fastapi import APIRouter, Path, Query, Response, status

router = APIRouter(prefix="/v1/admission", tags=["admission"])

NodeId = Annotated[str, Path(min_length=1, max_length=40)]


async def list_trajectories(
    container: ContainerDep,
    ctx: AdmissionCtx,
    q: Annotated[str | None, Query(max_length=100)] = None,
    field: Annotated[str | None, Query(max_length=20)] = None,
) -> TrajectoryListOut:
    """Published trajectories by field and text, with the caller's progress."""
    rows = await container.admission.trajectories.browse(ctx, q, field)
    return TrajectoryListOut(items=[TrajectorySummaryOut.of(s) for s in rows])


async def get_trajectory(
    slug: Annotated[str, Path(max_length=80)],
    container: ContainerDep,
    ctx: AdmissionCtx,
) -> TrajectoryDetailOut:
    """One published trajectory (curators also open drafts) with progress."""
    svc = container.admission.trajectories
    view = await svc.open(ctx, slug)
    return TrajectoryDetailOut.of(
        view,
        svc.resource_url,
        can_track=ctx.admission.is_applicant and view.trajectory.published,
    )


async def mark_node(
    trajectory_id: UUID,
    node_id: NodeId,
    body: NodeProgressIn,
    container: ContainerDep,
    ctx: StudentCtx,
) -> TrajectoryDetailOut:
    """Set the applicant's status of a node; null clears it."""
    svc = container.admission.trajectories
    view = await svc.mark(ctx, trajectory_id, node_id, body.status)
    return TrajectoryDetailOut.of(view, svc.resource_url, can_track=True)


async def staff_list(
    container: ContainerDep, ctx: AnyContext
) -> TrajectoryStaffListOut:
    """Every trajectory, drafts too (curators only)."""
    rows = await container.admission.trajectories.list_all(ctx)
    return TrajectoryStaffListOut(
        items=[
            TrajectorySummaryOut.of(
                TrajectorySummary(t, required=len(required_ids(t)), done=0)
            )
            for t in rows
        ]
    )


async def staff_get(
    trajectory_id: UUID, container: ContainerDep, ctx: AnyContext
) -> TrajectoryOut:
    """One trajectory for the editor."""
    svc = container.admission.trajectories
    return TrajectoryOut.of(await svc.get(ctx, trajectory_id), svc.resource_url)


async def staff_create(
    body: TrajectoryIn, container: ContainerDep, ctx: AnyContext
) -> TrajectoryOut:
    """Add a trajectory."""
    svc = container.admission.trajectories
    return TrajectoryOut.of(await svc.create(ctx, body.values()), svc.resource_url)


async def staff_update(
    trajectory_id: UUID, body: TrajectoryIn, container: ContainerDep, ctx: AnyContext
) -> TrajectoryOut:
    """Replace a trajectory."""
    svc = container.admission.trajectories
    saved = await svc.update(ctx, trajectory_id, body.values())
    return TrajectoryOut.of(saved, svc.resource_url)


async def staff_delete(
    trajectory_id: UUID, container: ContainerDep, ctx: AnyContext
) -> Response:
    """Delete a trajectory and every student's progress on it."""
    await container.admission.trajectories.delete(ctx, trajectory_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def staff_resources(
    container: ContainerDep,
    ctx: AnyContext,
    kind: ResourceKind = "lms_course",
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> ResourceHitListOut:
    """LMS courses or library books a curator may link to a node."""
    hits = await container.admission.trajectories.find_resources(ctx, kind, q)
    return ResourceHitListOut(items=[ResourceHitOut.of(h) for h in hits])


_R = router.add_api_route
_R(
    "/trajectories",
    list_trajectories,
    methods=["GET"],
    response_model=TrajectoryListOut,
    operation_id="admission_trajectories_list",
)
_R(
    "/trajectories/{slug}",
    get_trajectory,
    methods=["GET"],
    response_model=TrajectoryDetailOut,
    operation_id="admission_trajectories_get",
)
_R(
    "/trajectories/{trajectory_id}/progress/{node_id}",
    mark_node,
    methods=["PUT"],
    response_model=TrajectoryDetailOut,
    operation_id="admission_trajectories_mark_node",
)
_R(
    "/staff/trajectories",
    staff_list,
    methods=["GET"],
    response_model=TrajectoryStaffListOut,
    operation_id="admission_staff_trajectories_list",
)
_R(
    "/staff/trajectories",
    staff_create,
    methods=["POST"],
    status_code=status.HTTP_201_CREATED,
    response_model=TrajectoryOut,
    operation_id="admission_staff_trajectories_create",
)
_R(
    "/staff/trajectories/resources",
    staff_resources,
    methods=["GET"],
    response_model=ResourceHitListOut,
    operation_id="admission_staff_trajectories_resources",
)
_R(
    "/staff/trajectories/{trajectory_id}",
    staff_get,
    methods=["GET"],
    response_model=TrajectoryOut,
    operation_id="admission_staff_trajectories_get",
)
_R(
    "/staff/trajectories/{trajectory_id}",
    staff_update,
    methods=["PUT"],
    response_model=TrajectoryOut,
    operation_id="admission_staff_trajectories_update",
)
_R(
    "/staff/trajectories/{trajectory_id}",
    staff_delete,
    methods=["DELETE"],
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    operation_id="admission_staff_trajectories_delete",
)
