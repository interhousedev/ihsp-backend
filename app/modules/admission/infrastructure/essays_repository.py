"""SQL repository of essays, versions and the ideas board."""

from typing import Any, cast
from uuid import UUID

from app.modules.admission.domain.errors import (
    AdmissionConflictError,
    AdmissionNotFoundError,
)
from app.modules.admission.domain.essays import (
    Essay,
    EssayIdea,
    EssayKind,
    EssayLink,
    EssayStatus,
    EssayVersion,
    IdeaStatus,
    LinkKind,
    PlanSection,
    VersionSource,
)
from app.modules.admission.infrastructure.orm.profile import (
    EssayIdeaRow,
    EssayRow,
    EssayVersionRow,
)

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession


def _plan(raw: list[dict[str, Any]]) -> tuple[PlanSection, ...]:
    return tuple(
        PlanSection(str(s.get("heading", "")), str(s.get("note", ""))) for s in raw
    )


def _links(raw: list[dict[str, Any]]) -> tuple[EssayLink, ...]:
    return tuple(
        EssayLink(cast(LinkKind, str(link.get("kind"))), str(link.get("ref", "")))
        for link in raw
    )


def _essay(row: EssayRow) -> Essay:
    return Essay(
        id=row.id,
        student_id=row.student_id,
        kind=cast(EssayKind, row.kind),
        title=row.title,
        prompt_text=row.prompt_text,
        word_limit=row.word_limit,
        list_entry_id=row.list_entry_id,
        body=row.body,
        notes=row.notes,
        plan=_plan(row.plan or []),
        links=_links(row.links or []),
        status=cast(EssayStatus, row.status),
        current_version=row.current_version,
        last_snapshot_at=row.last_snapshot_at,
        lock_version=row.lock_version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _version(row: EssayVersionRow) -> EssayVersion:
    return EssayVersion(
        id=row.id,
        essay_id=row.essay_id,
        version=row.version,
        body=row.body,
        created_by=row.created_by,
        source=cast(VersionSource, row.source),
        name=row.name,
        shared=row.shared,
        word_count=row.word_count,
        created_at=row.created_at,
    )


def _idea(row: EssayIdeaRow) -> EssayIdea:
    return EssayIdea(
        id=row.id,
        student_id=row.student_id,
        body=row.body,
        essay_id=row.essay_id,
        tags=tuple(row.tags or ()),
        status=cast(IdeaStatus, row.status),
        sort_order=row.sort_order,
        lock_version=row.lock_version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _fill(row: EssayRow, essay: Essay) -> None:
    row.kind = essay.kind
    row.title = essay.title
    row.prompt_text = essay.prompt_text
    row.word_limit = essay.word_limit
    row.list_entry_id = essay.list_entry_id
    row.body = essay.body
    row.notes = essay.notes
    row.plan = [{"heading": s.heading, "note": s.note} for s in essay.plan]
    row.links = [{"kind": link.kind, "ref": link.ref} for link in essay.links]
    row.status = essay.status
    row.current_version = essay.current_version
    row.last_snapshot_at = essay.last_snapshot_at


class SqlEssayRepository:
    """Essays on an open session."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the session."""
        self._s = session

    async def list_for(self, student_id: UUID) -> list[Essay]:
        """Return the essays, newest edit first."""
        rows = await self._s.scalars(
            select(EssayRow)
            .where(EssayRow.student_id == student_id)
            .order_by(EssayRow.updated_at.desc(), EssayRow.id)
        )
        return [_essay(r) for r in rows]

    async def get(self, essay_id: UUID) -> Essay | None:
        """Return one essay."""
        row = await self._s.get(EssayRow, essay_id)
        return _essay(row) if row else None

    async def add(self, essay: Essay) -> Essay:
        """Insert an essay."""
        row = EssayRow(id=essay.id, student_id=essay.student_id, lock_version=0)
        _fill(row, essay)
        self._s.add(row)
        await self._s.flush()
        await self._s.refresh(row)
        return _essay(row)

    async def update(self, essay: Essay) -> Essay:
        """Store the fields and bump the lock version (compare-and-set)."""
        row = await self._s.get(EssayRow, essay.id, with_for_update=True)
        if row is None:
            raise AdmissionNotFoundError()
        if row.lock_version != essay.lock_version:
            raise AdmissionConflictError()
        _fill(row, essay)
        row.lock_version = essay.lock_version + 1
        await self._s.flush()
        await self._s.refresh(row)
        return _essay(row)

    async def delete(self, essay_id: UUID) -> None:
        """Delete the essay; versions and ideas cascade."""
        await self._s.execute(delete(EssayRow).where(EssayRow.id == essay_id))

    async def versions(self, essay_id: UUID) -> list[EssayVersion]:
        """Return the versions, newest first."""
        rows = await self._s.scalars(
            select(EssayVersionRow)
            .where(EssayVersionRow.essay_id == essay_id)
            .order_by(EssayVersionRow.version.desc())
        )
        return [_version(r) for r in rows]

    async def version(self, essay_id: UUID, version: int) -> EssayVersion | None:
        """Return one version."""
        row = await self._s.scalar(
            select(EssayVersionRow).where(
                EssayVersionRow.essay_id == essay_id,
                EssayVersionRow.version == version,
            )
        )
        return _version(row) if row else None

    async def add_version(self, version: EssayVersion) -> EssayVersion:
        """Insert a version."""
        row = EssayVersionRow(
            id=version.id,
            essay_id=version.essay_id,
            version=version.version,
            name=version.name,
            body=version.body,
            created_by=version.created_by,
            source=version.source,
            shared=version.shared,
            word_count=version.word_count,
        )
        self._s.add(row)
        await self._s.flush()
        await self._s.refresh(row)
        return _version(row)

    async def set_shared(
        self, essay_id: UUID, version: int, shared: bool
    ) -> EssayVersion | None:
        """Share or unshare one version."""
        row = await self._s.scalar(
            update(EssayVersionRow)
            .where(
                EssayVersionRow.essay_id == essay_id,
                EssayVersionRow.version == version,
            )
            .values(shared=shared)
            .returning(EssayVersionRow)
        )
        return _version(row) if row else None

    async def ideas_for(self, student_id: UUID) -> list[EssayIdea]:
        """Return the ideas board in display order."""
        rows = await self._s.scalars(
            select(EssayIdeaRow)
            .where(EssayIdeaRow.student_id == student_id)
            .order_by(EssayIdeaRow.sort_order, EssayIdeaRow.created_at)
        )
        return [_idea(r) for r in rows]

    async def get_idea(self, idea_id: UUID) -> EssayIdea | None:
        """Return one idea."""
        row = await self._s.get(EssayIdeaRow, idea_id)
        return _idea(row) if row else None

    async def add_idea(self, idea: EssayIdea) -> EssayIdea:
        """Insert an idea."""
        row = EssayIdeaRow(
            id=idea.id,
            student_id=idea.student_id,
            essay_id=idea.essay_id,
            body=idea.body,
            tags=list(idea.tags),
            status=idea.status,
            sort_order=idea.sort_order,
            lock_version=0,
        )
        self._s.add(row)
        await self._s.flush()
        await self._s.refresh(row)
        return _idea(row)

    async def update_idea(self, idea: EssayIdea) -> EssayIdea:
        """Store the idea (compare-and-set)."""
        row = await self._s.get(EssayIdeaRow, idea.id)
        if row is None:
            raise AdmissionNotFoundError()
        if row.lock_version != idea.lock_version:
            raise AdmissionConflictError()
        row.essay_id = idea.essay_id
        row.body = idea.body
        row.tags = list(idea.tags)
        row.status = idea.status
        row.sort_order = idea.sort_order
        row.lock_version = idea.lock_version + 1
        await self._s.flush()
        await self._s.refresh(row)
        return _idea(row)

    async def delete_idea(self, idea_id: UUID) -> None:
        """Delete an idea."""
        await self._s.execute(delete(EssayIdeaRow).where(EssayIdeaRow.id == idea_id))
