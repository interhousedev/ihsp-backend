"""SQL repository of topic labels, their links and the auto run state."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.notebooks.domain.labels import (
    LabelLink,
    LabelOrigin,
    LabelRun,
    LabelRunStatus,
    SourceLabel,
)
from app.modules.notebooks.infrastructure.orm.label import SourceLabel as LabelRow
from app.modules.notebooks.infrastructure.orm.label import (
    SourceLabelLink as LinkRow,
)
from app.modules.notebooks.infrastructure.orm.label import SourceLabelRun as RunRow

from sqlalchemy import Select, delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession


def _to_label(row: LabelRow, count: int) -> SourceLabel:
    return SourceLabel(
        id=row.id,
        notebook_id=row.notebook_id,
        name=row.name,
        emoji=row.emoji,
        position=int(row.position),
        origin=LabelOrigin(row.origin),
        created_at=row.created_at,
        source_count=count,
    )


def _to_run(row: RunRow) -> LabelRun:
    return LabelRun(
        notebook_id=row.notebook_id,
        status=LabelRunStatus(row.status),
        started_at=row.started_at,
        finished_at=row.finished_at,
        error=row.error,
        started_by=row.started_by,
    )


class SqlLabelRepository:
    """Labels of a notebook, their links to sources and the auto run state."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the unit of work's session."""
        self.session = session

    def _counted(self) -> Select[tuple[LabelRow, int]]:
        """`select(label, number of linked sources)`, to add conditions to."""
        return (
            select(LabelRow, func.count(LinkRow.source_id))
            .outerjoin(LinkRow, LinkRow.label_id == LabelRow.id)
            .group_by(LabelRow.id)
            .execution_options(populate_existing=True)
        )

    async def list_for_notebook(self, notebook_id: UUID) -> list[SourceLabel]:
        """The labels of a notebook by `position`, with their `source_count`."""
        stmt = (
            self._counted()
            .where(LabelRow.notebook_id == notebook_id)
            .order_by(LabelRow.position, LabelRow.id)
        )
        rows = (await self.session.execute(stmt)).all()
        return [_to_label(row, int(count)) for row, count in rows]

    async def get(self, label_id: UUID) -> SourceLabel | None:
        """The label with its `source_count`."""
        stmt = self._counted().where(LabelRow.id == label_id)
        found = (await self.session.execute(stmt)).first()
        return _to_label(found[0], int(found[1])) if found else None

    async def add(self, label: SourceLabel) -> None:
        """Insert a label."""
        self.session.add(
            LabelRow(
                id=label.id,
                notebook_id=label.notebook_id,
                name=label.name,
                emoji=label.emoji,
                position=label.position,
                origin=label.origin.value,
                created_at=label.created_at,
            )
        )
        await self.session.flush()

    async def save(self, label: SourceLabel) -> None:
        """Write the name, emoji, position and origin of a label."""
        row = await self.session.get(LabelRow, label.id)
        if row is None:
            return
        row.name = label.name
        row.emoji = label.emoji
        row.position = label.position
        row.origin = label.origin.value
        await self.session.flush()

    async def delete(self, label_ids: Sequence[UUID]) -> None:
        """Delete labels (their links cascade)."""
        if not label_ids:
            return
        await self.session.execute(
            delete(LabelRow).where(LabelRow.id.in_(label_ids)),
            execution_options={"synchronize_session": False},
        )

    async def links_for_notebook(self, notebook_id: UUID) -> list[LabelLink]:
        """Every link of the notebook's labels."""
        stmt = (
            select(LinkRow.source_id, LinkRow.label_id, LinkRow.origin)
            .join(LabelRow, LabelRow.id == LinkRow.label_id)
            .where(LabelRow.notebook_id == notebook_id)
            .order_by(LinkRow.source_id, LinkRow.label_id)
        )
        return [
            LabelLink(source_id, label_id, LabelOrigin(origin))
            for source_id, label_id, origin in (await self.session.execute(stmt)).all()
        ]

    async def replace_links(
        self, source_id: UUID, label_ids: Sequence[UUID], origin: LabelOrigin
    ) -> None:
        """Make exactly these labels the source's links, all with `origin`."""
        await self.session.execute(
            delete(LinkRow).where(LinkRow.source_id == source_id),
            execution_options={"synchronize_session": False},
        )
        await self.add_links([LabelLink(source_id, i, origin) for i in label_ids])

    async def add_links(self, links: Sequence[LabelLink]) -> None:
        """Insert links (a link that exists is left as it is)."""
        if not links:
            return
        stmt = (
            insert(LinkRow)
            .values(
                [
                    {
                        "source_id": link.source_id,
                        "label_id": link.label_id,
                        "origin": link.origin.value,
                    }
                    for link in links
                ]
            )
            .on_conflict_do_nothing()
        )
        await self.session.execute(stmt)

    async def delete_links(
        self, source_ids: Sequence[UUID], origin: LabelOrigin
    ) -> None:
        """Delete the links of `origin` that these sources have."""
        if not source_ids:
            return
        await self.session.execute(
            delete(LinkRow).where(
                LinkRow.source_id.in_(source_ids), LinkRow.origin == origin.value
            ),
            execution_options={"synchronize_session": False},
        )

    async def get_run(self, notebook_id: UUID) -> LabelRun | None:
        """The auto run state, None when the notebook never ran one."""
        stmt = (
            select(RunRow)
            .where(RunRow.notebook_id == notebook_id)
            .execution_options(populate_existing=True)
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return _to_run(row) if row is not None else None

    async def save_run(self, run: LabelRun) -> None:
        """Insert or update the auto run state."""
        values = {
            "status": run.status.value,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "error": run.error,
            "started_by": run.started_by,
        }
        stmt = (
            insert(RunRow)
            .values(notebook_id=run.notebook_id, **values)
            .on_conflict_do_update(index_elements=[RunRow.notebook_id], set_=values)
        )
        await self.session.execute(stmt)
