"""Ports: storage of trajectories and student progress, and the resource finder."""

from typing import Protocol
from uuid import UUID

from app.modules.admission.domain.trajectories import (
    NodeStatus,
    ResourceHit,
    ResourceKind,
    Trajectory,
)
from app.shared.actor import Actor


class TrajectorySlugTakenError(Exception):
    """Another trajectory already uses the slug."""


class TrajectoryRepository(Protocol):
    """Trajectories and the progress students mark on them."""

    async def all(self, *, published_only: bool) -> list[Trajectory]:
        """Trajectories ordered by field and slug."""
        ...

    async def get(self, trajectory_id: UUID) -> Trajectory | None:
        """One trajectory, else None."""
        ...

    async def get_by_slug(self, slug: str) -> Trajectory | None:
        """One trajectory by slug, else None."""
        ...

    async def save(self, trajectory: Trajectory) -> Trajectory:
        """Insert or overwrite; raise `TrajectorySlugTakenError` on a slug clash."""
        ...

    async def delete(self, trajectory_id: UUID) -> bool:
        """Delete a trajectory and its progress; return whether it existed."""
        ...

    async def progress(
        self, student_id: UUID, trajectory_ids: list[UUID]
    ) -> dict[UUID, dict[str, str]]:
        """Node statuses of the student, by trajectory then node id."""
        ...

    async def set_progress(
        self,
        student_id: UUID,
        trajectory_id: UUID,
        node_id: str,
        status: NodeStatus | None,
    ) -> None:
        """Store a node status; None clears it."""
        ...


class TrajectoryResources(Protocol):
    """Finds LMS courses and library books a curator may link."""

    async def find(
        self, actor: Actor, kind: ResourceKind, query: str | None, limit: int
    ) -> list[ResourceHit]:
        """Courses or books visible to the actor matching the query."""
        ...
