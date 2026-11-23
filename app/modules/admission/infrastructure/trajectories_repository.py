"""SQL storage of trajectories and student progress; each call is a session."""

from dataclasses import asdict
from typing import Any
from uuid import UUID

from app.modules.admission.domain.trajectories import (
    NodeStatus,
    ResourceHit,
    ResourceKind,
    Trajectory,
    trajectory_of_dict,
)
from app.modules.admission.infrastructure.orm.trajectories import (
    TrajectoryProgressRow,
    TrajectoryRow,
)
from app.modules.admission.ports.courses import CourseSources
from app.modules.admission.ports.trajectories import TrajectorySlugTakenError
from app.shared.actor import Actor
from app.shared.contracts.library import LibraryBookCatalogue
from app.shared.ids import new_id

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _trajectory(row: TrajectoryRow) -> Trajectory:
    stages, edges = trajectory_of_dict({"stages": row.stages, "edges": row.edges})
    return Trajectory(
        id=row.id,
        slug=row.slug,
        field=row.field,
        title=dict(row.title or {}),
        description=dict(row.description or {}),
        published=row.published,
        stages=stages,
        edges=edges,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _json(value: Any) -> Any:
    """Plain JSON of a dataclass tree (tuples become lists)."""
    if isinstance(value, dict):
        return {k: _json(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_json(v) for v in value]
    return value


class SqlTrajectoryRepository:
    """Trajectories and the progress rows of students."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Keep the sessionmaker."""
        self._sm = sessionmaker

    async def all(self, *, published_only: bool) -> list[Trajectory]:
        """Trajectories ordered by field and slug."""
        stmt = select(TrajectoryRow).order_by(TrajectoryRow.field, TrajectoryRow.slug)
        if published_only:
            stmt = stmt.where(TrajectoryRow.published.is_(True))
        async with self._sm() as session:
            return [_trajectory(r) for r in (await session.scalars(stmt)).all()]

    async def get(self, trajectory_id: UUID) -> Trajectory | None:
        """One trajectory, else None."""
        async with self._sm() as session:
            row = await session.get(TrajectoryRow, trajectory_id)
        return _trajectory(row) if row else None

    async def get_by_slug(self, slug: str) -> Trajectory | None:
        """One trajectory by slug, else None."""
        async with self._sm() as session:
            row = await session.scalar(
                select(TrajectoryRow).where(TrajectoryRow.slug == slug)
            )
        return _trajectory(row) if row else None

    async def save(self, trajectory: Trajectory) -> Trajectory:
        """Insert or overwrite a trajectory."""
        try:
            async with self._sm() as session, session.begin():
                row = await session.get(TrajectoryRow, trajectory.id)
                if row is None:
                    row = TrajectoryRow(id=trajectory.id)
                    session.add(row)
                row.slug = trajectory.slug
                row.field = trajectory.field
                row.title = dict(trajectory.title)
                row.description = dict(trajectory.description)
                row.published = trajectory.published
                row.stages = _json([asdict(s) for s in trajectory.stages])
                row.edges = _json([asdict(e) for e in trajectory.edges])
                await session.flush()
                await session.refresh(row)
                return _trajectory(row)
        except IntegrityError as exc:
            raise TrajectorySlugTakenError from exc

    async def delete(self, trajectory_id: UUID) -> bool:
        """Delete a trajectory; progress rows cascade."""
        async with self._sm() as session, session.begin():
            result = await session.execute(
                delete(TrajectoryRow)
                .where(TrajectoryRow.id == trajectory_id)
                .returning(TrajectoryRow.id)
            )
            return result.first() is not None

    async def progress(
        self, student_id: UUID, trajectory_ids: list[UUID]
    ) -> dict[UUID, dict[str, str]]:
        """Node statuses of the student, by trajectory then node id."""
        out: dict[UUID, dict[str, str]] = {}
        async with self._sm() as session:
            rows = await session.scalars(
                select(TrajectoryProgressRow).where(
                    TrajectoryProgressRow.student_id == student_id,
                    TrajectoryProgressRow.trajectory_id.in_(trajectory_ids),
                )
            )
            for r in rows:
                out.setdefault(r.trajectory_id, {})[r.node_id] = r.status
        return out

    async def set_progress(
        self,
        student_id: UUID,
        trajectory_id: UUID,
        node_id: str,
        status: NodeStatus | None,
    ) -> None:
        """Upsert or clear one node status."""
        async with self._sm() as session, session.begin():
            if status is None:
                await session.execute(
                    delete(TrajectoryProgressRow).where(
                        TrajectoryProgressRow.student_id == student_id,
                        TrajectoryProgressRow.trajectory_id == trajectory_id,
                        TrajectoryProgressRow.node_id == node_id,
                    )
                )
                return
            stmt = pg_insert(TrajectoryProgressRow).values(
                id=new_id(),
                student_id=student_id,
                trajectory_id=trajectory_id,
                node_id=node_id,
                status=status,
            )
            await session.execute(
                stmt.on_conflict_do_update(
                    index_elements=["student_id", "trajectory_id", "node_id"],
                    set_={"status": stmt.excluded.status, "updated_at": func.now()},
                )
            )


class TrajectoryResourceFinder:
    """LMS courses through `CourseSources`, books through the library contract."""

    def __init__(
        self, sources: CourseSources, library: LibraryBookCatalogue | None
    ) -> None:
        """Keep the sources; `library` is None where the library is off."""
        self._sources = sources
        self._library = library

    async def find(
        self, actor: Actor, kind: ResourceKind, query: str | None, limit: int
    ) -> list[ResourceHit]:
        """Courses or books visible to the actor matching the query."""
        if kind == "lms_course":
            return [
                ResourceHit(
                    kind="lms_course",
                    ref=c.id,
                    title=c.title,
                    subtitle=c.summary,
                    url=c.url,
                )
                for c in await self._sources.lms_find(actor, query, limit)
            ]
        if kind == "library_book" and self._library is not None:
            page = await self._library.search_books(actor, query, limit=limit, offset=0)
            return [
                ResourceHit(
                    kind="library_book",
                    ref=str(b.id),
                    title=b.title,
                    subtitle=b.author_label,
                    url="",
                )
                for b in page.items
            ]
        return []
