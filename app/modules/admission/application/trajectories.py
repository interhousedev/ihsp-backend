"""Educational trajectories: browsing and progress for students, editing for staff."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any, cast
from urllib.parse import urlencode
from uuid import UUID

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
)
from app.modules.admission.domain.permissions import Permission
from app.modules.admission.domain.trajectories import (
    NODE_STATUSES,
    NodeStatus,
    Resource,
    ResourceHit,
    ResourceKind,
    Trajectory,
    clean_trajectory,
    done_count,
    required_ids,
)
from app.modules.admission.ports.repositories import AuditEvent
from app.modules.admission.ports.trajectories import (
    TrajectoryRepository,
    TrajectoryResources,
    TrajectorySlugTakenError,
)
from app.modules.admission.ports.unit_of_work import UowFactory
from app.shared.base_error import ValidationFailedError
from app.shared.ids import new_id

CanCurate = Callable[[AdmissionContext], bool]
FIND_LIMIT = 20


@dataclass(frozen=True, slots=True)
class TrajectorySummary:
    """A trajectory in a list, with the caller's progress."""

    trajectory: Trajectory
    required: int
    done: int


@dataclass(frozen=True, slots=True)
class TrajectoryView:
    """A trajectory and the caller's node statuses."""

    trajectory: Trajectory
    progress: dict[str, str]


class TrajectoryService:
    """Published trajectories for everyone in admission; the editor for curators."""

    def __init__(
        self,
        repo: TrajectoryRepository,
        resources: TrajectoryResources,
        uow_factory: UowFactory,
        can_curate: CanCurate,
        lms_url: str,
        library_url: str,
    ) -> None:
        """Keep the storage, the resource finder, the audit and the curator rule."""
        self._repo = repo
        self._resources = resources
        self._uow = uow_factory
        self._can_curate = can_curate
        self._lms = lms_url.rstrip("/")
        self._lib = library_url.rstrip("/")

    def resource_url(self, r: Resource) -> str:
        """The page a resource opens."""
        if r.kind == "lms_course":
            return f"{self._lms}/course/{r.ref}/"
        if r.kind == "library_book":
            return f"{self._lib}/item/?{urlencode({'id': r.ref})}"
        return r.ref

    def may_curate(self, ctx: AdmissionContext) -> bool:
        """Whether the caller edits trajectories."""
        return self._can_curate(ctx)

    def _require_curator(self, ctx: AdmissionContext) -> None:
        if not self._can_curate(ctx):
            raise AdmissionForbiddenError(
                params={"permission": Permission.CATALOG_CURATE.value}
            )

    async def _progress_of(
        self, ctx: AdmissionContext, ids: list[UUID]
    ) -> dict[UUID, dict[str, str]]:
        if not ctx.admission.is_applicant or not ids:
            return {}
        return await self._repo.progress(ctx.user_id, ids)

    # - - - students - - -

    async def browse(
        self, ctx: AdmissionContext, query: str | None, field: str | None
    ) -> list[TrajectorySummary]:
        """Published trajectories, filtered by field and text."""
        q = (query or "").strip()
        rows = [
            t
            for t in await self._repo.all(published_only=True)
            if (field is None or t.field == field) and (not q or t.matches(q))
        ]
        progress = await self._progress_of(ctx, [t.id for t in rows])
        return [
            TrajectorySummary(
                trajectory=t,
                required=len(required_ids(t)),
                done=done_count(t, progress.get(t.id, {})),
            )
            for t in rows
        ]

    async def open(self, ctx: AdmissionContext, slug: str) -> TrajectoryView:
        """A published trajectory (curators also see drafts) with progress."""
        found = await self._repo.get_by_slug(slug)
        if found is None or not (found.published or self._can_curate(ctx)):
            raise AdmissionNotFoundError()
        progress = await self._progress_of(ctx, [found.id])
        return TrajectoryView(found, progress.get(found.id, {}))

    async def mark(
        self,
        ctx: AdmissionContext,
        trajectory_id: UUID,
        node_id: str,
        status: str | None,
    ) -> TrajectoryView:
        """Set the applicant's status of a node; None clears it."""
        found = await self._repo.get(trajectory_id)
        if found is None or not found.published:
            raise AdmissionNotFoundError()
        if node_id not in {n.id for n in found.nodes()}:
            raise AdmissionNotFoundError()
        if status is not None and status not in NODE_STATUSES:
            raise ValidationFailedError(params={"field": "status"})
        await self._repo.set_progress(
            ctx.user_id, trajectory_id, node_id, cast(NodeStatus | None, status)
        )
        progress = await self._repo.progress(ctx.user_id, [trajectory_id])
        return TrajectoryView(found, progress.get(trajectory_id, {}))

    # - - - curators - - -

    async def list_all(self, ctx: AdmissionContext) -> list[Trajectory]:
        """Every trajectory including drafts."""
        self._require_curator(ctx)
        return await self._repo.all(published_only=False)

    async def get(self, ctx: AdmissionContext, trajectory_id: UUID) -> Trajectory:
        """One trajectory for the editor."""
        self._require_curator(ctx)
        found = await self._repo.get(trajectory_id)
        if found is None:
            raise AdmissionNotFoundError()
        return found

    async def create(
        self, ctx: AdmissionContext, values: Mapping[str, Any]
    ) -> Trajectory:
        """Add a trajectory."""
        self._require_curator(ctx)
        saved = await self._save(Trajectory(id=new_id(), **clean_trajectory(values)))
        await self._audit(ctx, "trajectory.created", saved.id)
        return saved

    async def update(
        self, ctx: AdmissionContext, trajectory_id: UUID, values: Mapping[str, Any]
    ) -> Trajectory:
        """Replace the editable fields of a trajectory."""
        self._require_curator(ctx)
        current = await self._repo.get(trajectory_id)
        if current is None:
            raise AdmissionNotFoundError()
        saved = await self._save(
            Trajectory(
                id=current.id,
                created_at=current.created_at,
                **clean_trajectory(values),
            )
        )
        await self._audit(ctx, "trajectory.edited", saved.id)
        return saved

    async def delete(self, ctx: AdmissionContext, trajectory_id: UUID) -> None:
        """Remove a trajectory with every student's progress on it."""
        self._require_curator(ctx)
        if not await self._repo.delete(trajectory_id):
            raise AdmissionNotFoundError()
        await self._audit(ctx, "trajectory.deleted", trajectory_id)

    async def find_resources(
        self, ctx: AdmissionContext, kind: ResourceKind, query: str | None
    ) -> list[ResourceHit]:
        """LMS courses or library books to link to a node."""
        self._require_curator(ctx)
        q = (query or "").strip() or None
        hits = await self._resources.find(ctx.actor, kind, q, FIND_LIMIT)
        return [
            replace(h, url=self.resource_url(Resource(h.kind, h.ref, h.title)))
            for h in hits
        ]

    async def _save(self, trajectory: Trajectory) -> Trajectory:
        try:
            return await self._repo.save(trajectory)
        except TrajectorySlugTakenError:
            raise ValidationFailedError(
                params={"field": "slug", "reason": "taken"}
            ) from None

    async def _audit(self, ctx: AdmissionContext, action: str, oid: UUID) -> None:
        async with self._uow() as uow:
            uow.access.audit(
                AuditEvent(
                    action=action,
                    actor_id=ctx.user_id,
                    student_id=None,
                    object_type="trajectory",
                    object_id=oid,
                )
            )
            await uow.commit()
