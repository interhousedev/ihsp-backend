"""SQLAlchemy repository of immutable step revisions."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.lms.domain.authoring.content_edit import collect_ids
from app.modules.lms.domain.authoring.entities import StepRevision
from app.modules.lms.domain.authoring.enums import RevisionKind
from app.modules.lms.infrastructure.orm import StepRevision as RevisionRow
from app.modules.lms.infrastructure.orm import TestAttempt as AttemptRow
from app.shared.ids import new_id

from sqlalchemy import delete, exists, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession


class SqlRevisionRepository:
    """Reads and writes `lms.step_revisions`."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the unit of work's session."""
        self.session = session

    async def ensure(
        self,
        *,
        step_id: UUID,
        content: dict[str, Any],
        content_hash: str,
        kind: RevisionKind,
        label: str | None,
        file_ids: Sequence[UUID],
        created_by: UUID,
        now: datetime,
    ) -> StepRevision:
        """Insert a revision or reuse the one with the same hash (updating a label)."""
        insert = pg_insert(RevisionRow).values(
            id=new_id(),
            step_id=step_id,
            content=content,
            content_hash=content_hash,
            kind=kind.value,
            label=label,
            file_ids=list(file_ids),
            created_by=created_by,
            created_at=now,
            updated_at=now,
        )
        statement = (
            insert.on_conflict_do_update(
                index_elements=[RevisionRow.step_id, RevisionRow.content_hash],
                set_={"label": func.coalesce(insert.excluded.label, RevisionRow.label)},
            )
            .returning(RevisionRow)
            .execution_options(populate_existing=True)
        )
        row = (await self.session.execute(statement)).scalar_one()
        return _to_entity(row)

    async def get(self, revision_id: UUID) -> StepRevision | None:
        """Return the revision, or None."""
        statement = (
            select(RevisionRow)
            .where(RevisionRow.id == revision_id)
            .execution_options(populate_existing=True)
        )
        row = (await self.session.scalars(statement)).one_or_none()
        return None if row is None else _to_entity(row)

    async def get_many(self, revision_ids: Sequence[UUID]) -> dict[UUID, StepRevision]:
        """Return the revisions that exist, by ID."""
        if not revision_ids:
            return {}
        statement = (
            select(RevisionRow)
            .where(RevisionRow.id.in_(list(revision_ids)))
            .execution_options(populate_existing=True)
        )
        return {r.id: _to_entity(r) for r in (await self.session.scalars(statement))}

    async def list_for_history(self, step_id: UUID, limit: int) -> list[StepRevision]:
        """Return published and checkpoint revisions of a step, newest first."""
        statement = (
            select(RevisionRow)
            .where(
                RevisionRow.step_id == step_id,
                (RevisionRow.kind.in_(["publish", "checkpoint"]))
                | (RevisionRow.published_at.is_not(None)),
            )
            .order_by(RevisionRow.created_at.desc(), RevisionRow.id.desc())
            .limit(limit)
            .execution_options(populate_existing=True)
        )
        return [_to_entity(r) for r in (await self.session.scalars(statement))]

    async def known_ids(self, step_id: UUID) -> set[str]:
        """Return every block, question, option and card ID in any revision."""
        contents = await self.session.scalars(
            select(RevisionRow.content).where(RevisionRow.step_id == step_id)
        )
        found: set[str] = set()
        for content in contents:
            found |= collect_ids(content)
        return found

    async def mark_published(self, revision_ids: Sequence[UUID], now: datetime) -> None:
        """Set `published_at` where it is still empty."""
        if not revision_ids:
            return
        await self.session.execute(
            update(RevisionRow)
            .where(
                RevisionRow.id.in_(list(revision_ids)),
                RevisionRow.published_at.is_(None),
            )
            .values(published_at=now)
            .execution_options(synchronize_session=False)
        )

    async def prune_checkpoints(
        self,
        *,
        keep: int,
        step_id: UUID | None = None,
        protect: Sequence[UUID] = (),
    ) -> int:
        """Delete checkpoints beyond the newest `keep` per step; return the count.

        Revisions that were published, are used by attempts or are listed in
        `protect` are never deleted.
        """
        ranked = select(
            RevisionRow.id.label("id"),
            func.row_number()
            .over(
                partition_by=RevisionRow.step_id,
                order_by=(RevisionRow.created_at.desc(), RevisionRow.id.desc()),
            )
            .label("rank"),
        ).where(RevisionRow.kind == RevisionKind.CHECKPOINT.value)
        if step_id is not None:
            ranked = ranked.where(RevisionRow.step_id == step_id)
        subquery = ranked.subquery()
        statement = (
            delete(RevisionRow)
            .where(
                RevisionRow.id.in_(select(subquery.c.id).where(subquery.c.rank > keep)),
                RevisionRow.published_at.is_(None),
                ~_used_by_attempt(),
            )
            .returning(RevisionRow.id)
            .execution_options(synchronize_session=False)
        )
        if protect:
            statement = statement.where(RevisionRow.id.not_in(list(protect)))
        return len((await self.session.execute(statement)).all())

    async def prune_previews(self, *, older_than: datetime) -> int:
        """Delete old preview revisions that were not published or attempted."""
        statement = (
            delete(RevisionRow)
            .where(
                RevisionRow.kind == RevisionKind.PREVIEW.value,
                RevisionRow.created_at < older_than,
                RevisionRow.published_at.is_(None),
                ~_used_by_attempt(),
            )
            .returning(RevisionRow.id)
            .execution_options(synchronize_session=False)
        )
        return len((await self.session.execute(statement)).all())


def _used_by_attempt() -> Any:  # noqa: ANN401 - a SQLAlchemy EXISTS clause
    return exists().where(AttemptRow.revision_id == RevisionRow.id)


def _to_entity(row: RevisionRow) -> StepRevision:
    return StepRevision(
        id=row.id,
        step_id=row.step_id,
        content=row.content,
        content_hash=row.content_hash,
        kind=RevisionKind(row.kind),
        created_by=row.created_by,
        created_at=row.created_at,
        file_ids=list(row.file_ids),
        label=row.label,
        published_at=row.published_at,
    )
