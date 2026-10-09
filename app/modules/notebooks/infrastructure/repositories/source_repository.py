"""SQL repository of sources."""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from app.modules.notebooks.domain.entities import Citation, Source, SourceGuide
from app.modules.notebooks.domain.enums import (
    GuideStatus,
    SourceFailure,
    SourceKind,
    SourceStatus,
)
from app.modules.notebooks.infrastructure.orm.label import SourceLabel as LabelRow
from app.modules.notebooks.infrastructure.orm.label import SourceLabelLink as LinkRow
from app.modules.notebooks.infrastructure.orm.notebook import Notebook as NotebookRow
from app.modules.notebooks.infrastructure.orm.source import Source as SourceRow

from sqlalchemy import Select, delete, func, select, update
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

_USABLE = [SourceStatus.READY.value, SourceStatus.STALE.value]
_UNFINISHED = [SourceStatus.PROCESSING.value, SourceStatus.PENDING.value]
# The ids of a source's labels in label order, read with the source (no N+1).
_LABEL_IDS = (
    select(func.array_agg(aggregate_order_by(LinkRow.label_id, LabelRow.position)))
    .select_from(LinkRow)
    .join(LabelRow, LabelRow.id == LinkRow.label_id)
    .where(LinkRow.source_id == SourceRow.id)
    .scalar_subquery()
)


def _to_entity(row: SourceRow, label_ids: list[UUID] | None = None) -> Source:
    return Source(
        id=row.id,
        notebook_id=row.notebook_id,
        owner_id=row.owner_id,
        kind=SourceKind(row.kind),
        title=row.title,
        position=int(row.position),
        created_at=row.created_at,
        updated_at=row.updated_at,
        ref=dict(row.ref or {}),
        ref_key=row.ref_key,
        origin=dict(row.origin) if row.origin is not None else None,
        selected=row.selected,
        status=SourceStatus(row.status),
        failure=SourceFailure(row.failure) if row.failure else None,
        body_md=row.body_md,
        citations=(
            [Citation.model_validate(c) for c in row.citations]
            if row.citations is not None
            else None
        ),
        content_hash=row.content_hash,
        document_id=row.document_id,
        upstream_version=row.upstream_version,
        word_count=int(row.word_count),
        char_count=int(row.char_count),
        token_estimate=int(row.token_estimate),
        passage_count=int(row.passage_count),
        guide=SourceGuide.model_validate(row.guide) if row.guide is not None else None,
        guide_status=GuideStatus(row.guide_status),
        text_synced_at=row.text_synced_at,
        label_ids=list(label_ids or []),
    )


def _apply(row: SourceRow, source: Source) -> None:
    row.notebook_id = source.notebook_id
    row.owner_id = source.owner_id
    row.kind = source.kind.value
    row.ref = source.ref
    row.ref_key = source.ref_key
    row.title = source.title
    row.origin = source.origin
    row.position = source.position
    row.selected = source.selected
    row.status = source.status.value
    row.failure = source.failure.value if source.failure else None
    row.body_md = source.body_md
    row.citations = (
        [c.model_dump(mode="json") for c in source.citations]
        if source.citations is not None
        else None
    )
    row.content_hash = source.content_hash
    row.document_id = source.document_id
    row.upstream_version = source.upstream_version
    row.word_count = source.word_count
    row.char_count = source.char_count
    row.token_estimate = source.token_estimate
    row.passage_count = source.passage_count
    row.guide = source.guide.model_dump(mode="json") if source.guide else None
    row.guide_status = source.guide_status.value
    row.text_synced_at = source.text_synced_at
    row.created_at = source.created_at
    row.updated_at = source.updated_at


class SqlSourceRepository:
    """Sources in `notebooks.sources`."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the unit of work's session."""
        self.session = session

    async def add(self, source: Source) -> None:
        """Insert a new source."""
        row = SourceRow(id=source.id)
        _apply(row, source)
        self.session.add(row)
        await self.session.flush()

    async def _load(self, stmt: Select[tuple[SourceRow]]) -> list[Source]:
        """Run a query and convert the rows (refreshing rows the session holds)."""
        stmt = stmt.add_columns(_LABEL_IDS).execution_options(populate_existing=True)
        return [
            _to_entity(row, label_ids)
            for row, label_ids in (await self.session.execute(stmt)).all()
        ]

    async def get(self, source_id: UUID) -> Source | None:
        """Return the source."""
        found = await self._load(select(SourceRow).where(SourceRow.id == source_id))
        return found[0] if found else None

    async def get_for_update(self, source_id: UUID) -> Source | None:
        """Return the source and lock its row until the transaction ends."""
        stmt = select(SourceRow).where(SourceRow.id == source_id).with_for_update()
        found = await self._load(stmt)
        return found[0] if found else None

    async def save(self, source: Source) -> None:
        """Write the source's stored fields, `updated_at` exactly as given."""
        stmt = select(SourceRow).where(SourceRow.id == source.id)
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return
        _apply(row, source)
        flag_modified(row, "updated_at")
        await self.session.flush()

    async def delete(self, source_id: UUID) -> None:
        """Delete the source (its passages cascade)."""
        await self.session.execute(
            delete(SourceRow).where(SourceRow.id == source_id),
            execution_options={"synchronize_session": False},
        )

    async def list_for_notebook(self, notebook_id: UUID) -> list[Source]:
        """All sources of a notebook ordered by `position`."""
        stmt = (
            select(SourceRow)
            .where(SourceRow.notebook_id == notebook_id)
            .order_by(SourceRow.position, SourceRow.id)
        )
        return await self._load(stmt)

    async def get_many(self, source_ids: Sequence[UUID]) -> list[Source]:
        """The sources that exist, in the order of `source_ids`."""
        if not source_ids:
            return []
        found = {
            s.id: s
            for s in await self._load(
                select(SourceRow).where(SourceRow.id.in_(source_ids))
            )
        }
        return [found[i] for i in dict.fromkeys(source_ids) if i in found]

    async def count_for_notebook(self, notebook_id: UUID) -> int:
        """How many sources the notebook has (any status)."""
        stmt = select(func.count(SourceRow.id)).where(
            SourceRow.notebook_id == notebook_id
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def total_chars(self, notebook_id: UUID) -> int:
        """Sum of `char_count` over the notebook's usable (ready/stale) sources."""
        stmt = select(func.coalesce(func.sum(SourceRow.char_count), 0)).where(
            SourceRow.notebook_id == notebook_id, SourceRow.status.in_(_USABLE)
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def next_position(self, notebook_id: UUID) -> int:
        """`max(position) + 1`, 1 for an empty notebook."""
        stmt = select(func.coalesce(func.max(SourceRow.position), 0) + 1).where(
            SourceRow.notebook_id == notebook_id
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def ref_key_exists(self, notebook_id: UUID, ref_key: str) -> bool:
        """True if the notebook already has a source with this duplicate key."""
        stmt = select(
            select(SourceRow.id)
            .where(SourceRow.notebook_id == notebook_id, SourceRow.ref_key == ref_key)
            .exists()
        )
        return bool((await self.session.execute(stmt)).scalar_one())

    async def set_selected(
        self, notebook_id: UUID, selected: bool, ids: Sequence[UUID] | None
    ) -> None:
        """Set the checkbox of the given sources (all of the notebook when None).

        `updated_at` is left alone: a checkbox is not a change of the source.
        """
        stmt = (
            update(SourceRow)
            .where(SourceRow.notebook_id == notebook_id)
            .values(selected=selected, updated_at=SourceRow.updated_at)
        )
        if ids is not None:
            if not ids:
                return
            stmt = stmt.where(SourceRow.id.in_(ids))
        await self.session.execute(
            stmt, execution_options={"synchronize_session": False}
        )

    async def list_by_ref_keys(self, ref_keys: Sequence[str]) -> list[Source]:
        """Sources of any notebook with these duplicate keys (not deleted notebooks)."""
        if not ref_keys:
            return []
        stmt = (
            select(SourceRow)
            .join(NotebookRow, NotebookRow.id == SourceRow.notebook_id)
            .where(SourceRow.ref_key.in_(ref_keys), NotebookRow.deleted_at.is_(None))
            .order_by(SourceRow.id)
        )
        return await self._load(stmt)

    async def list_for_sweep(
        self,
        kinds: Sequence[SourceKind],
        statuses: Sequence[SourceStatus],
        *,
        after_id: UUID | None,
        limit: int,
    ) -> list[Source]:
        """Sources of the kinds and statuses ordered by id, after `after_id`."""
        stmt = select(SourceRow).where(
            SourceRow.kind.in_([k.value for k in kinds]),
            SourceRow.status.in_([s.value for s in statuses]),
        )
        if after_id is not None:
            stmt = stmt.where(SourceRow.id > after_id)
        return await self._load(stmt.order_by(SourceRow.id).limit(limit))

    async def stuck_processing(
        self, updated_before: datetime, limit: int
    ) -> list[Source]:
        """Sources in `processing` (or `pending`) not updated since the cutoff."""
        stmt = (
            select(SourceRow)
            .where(
                SourceRow.status.in_(_UNFINISHED), SourceRow.updated_at < updated_before
            )
            .order_by(SourceRow.updated_at, SourceRow.id)
            .limit(limit)
        )
        return await self._load(stmt)
