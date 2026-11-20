"""SQL repository of essays, versions and the ideas board.

Essay text is sealed here (see `orm.sealed`): rows hold ciphertext, the domain
objects that leave this module hold plaintext.
"""

import json
from typing import Any, cast
from uuid import UUID

from app.modules.admission.domain.errors import (
    AdmissionConflictError,
    AdmissionNotFoundError,
)
from app.modules.admission.domain.essay_flow import PromptTarget
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
from app.modules.admission.infrastructure.orm.sealed import to_json
from app.modules.admission.ports.essay_crypto import EssayCipher

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


def _targets(raw: list[dict[str, Any]]) -> tuple[PromptTarget, ...]:
    return tuple(
        PromptTarget(
            UUID(t["institution_id"]) if t.get("institution_id") else None,
            int(t["position"]),
            str(t.get("prompt", "")),
            t.get("word_limit"),
        )
        for t in raw
    )


def _target_json(t: PromptTarget) -> dict[str, Any]:
    return {
        "institution_id": None if t.institution_id is None else str(t.institution_id),
        "position": t.position,
        "prompt": t.prompt,
        "word_limit": t.word_limit,
    }


class SqlEssayRepository:
    """Essays on an open session; text columns are sealed with the owner's key."""

    def __init__(self, session: AsyncSession, cipher: EssayCipher) -> None:
        """Bind the session and the essay cipher."""
        self._s = session
        self._c = cipher

    async def _seal(self, owner: UUID, rid: UUID, column: str, text: str) -> bytes:
        return await self._c.seal(owner, rid, column, text)

    async def _open(self, owner: UUID, rid: UUID, column: str, blob: bytes) -> str:
        return await self._c.open(owner, rid, column, blob)

    async def _owner(self, essay_id: UUID) -> UUID | None:
        owner: UUID | None = await self._s.scalar(
            select(EssayRow.student_id).where(EssayRow.id == essay_id)
        )
        return owner

    async def _essay(self, row: EssayRow) -> Essay:
        o, rid = row.student_id, row.id
        plan = json.loads(await self._open(o, rid, "plan", row.plan))
        return Essay(
            id=row.id,
            student_id=row.student_id,
            kind=cast(EssayKind, row.kind),
            title=await self._open(o, rid, "title", row.title),
            prompt_text=row.prompt_text,
            word_limit=row.word_limit,
            list_entry_id=row.list_entry_id,
            body=await self._open(o, rid, "body", row.body),
            notes=await self._open(o, rid, "notes", row.notes),
            plan=_plan(plan or []),
            links=_links(row.links or []),
            targets=_targets(row.targets or []),
            forked_from=row.forked_from,
            status=cast(EssayStatus, row.status),
            current_version=row.current_version,
            last_snapshot_at=row.last_snapshot_at,
            lock_version=row.lock_version,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def _version(self, owner: UUID, row: EssayVersionRow) -> EssayVersion:
        name = row.name
        opened = None if name is None else await self._open(owner, row.id, "name", name)
        return EssayVersion(
            id=row.id,
            essay_id=row.essay_id,
            version=row.version,
            body=await self._open(owner, row.id, "body", row.body),
            created_by=row.created_by,
            source=cast(VersionSource, row.source),
            name=opened,
            shared=row.shared,
            word_count=row.word_count,
            created_at=row.created_at,
        )

    async def _idea(self, row: EssayIdeaRow) -> EssayIdea:
        o, rid = row.student_id, row.id
        tags = json.loads(await self._open(o, rid, "tags", row.tags))
        return EssayIdea(
            id=row.id,
            student_id=row.student_id,
            body=await self._open(o, rid, "body", row.body),
            essay_id=row.essay_id,
            tags=tuple(str(t) for t in tags),
            status=cast(IdeaStatus, row.status),
            sort_order=row.sort_order,
            lock_version=row.lock_version,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def _fill(self, row: EssayRow, essay: Essay) -> None:
        o, rid = essay.student_id, essay.id
        plan = [{"heading": s.heading, "note": s.note} for s in essay.plan]
        row.kind = essay.kind
        row.title = await self._seal(o, rid, "title", essay.title)
        row.prompt_text = essay.prompt_text
        row.word_limit = essay.word_limit
        row.list_entry_id = essay.list_entry_id
        row.body = await self._seal(o, rid, "body", essay.body)
        row.notes = await self._seal(o, rid, "notes", essay.notes)
        row.plan = await self._seal(o, rid, "plan", to_json(plan))
        row.links = [{"kind": link.kind, "ref": link.ref} for link in essay.links]
        row.targets = [_target_json(t) for t in essay.targets]
        row.forked_from = essay.forked_from
        row.status = essay.status
        row.current_version = essay.current_version
        row.last_snapshot_at = essay.last_snapshot_at

    async def _fill_idea(self, row: EssayIdeaRow, idea: EssayIdea) -> None:
        o, rid = idea.student_id, idea.id
        row.essay_id = idea.essay_id
        row.body = await self._seal(o, rid, "body", idea.body)
        row.tags = await self._seal(o, rid, "tags", to_json(list(idea.tags)))
        row.status = idea.status
        row.sort_order = idea.sort_order

    async def list_for(self, student_id: UUID) -> list[Essay]:
        """Return the essays, newest edit first."""
        rows = await self._s.scalars(
            select(EssayRow)
            .where(EssayRow.student_id == student_id)
            .order_by(EssayRow.updated_at.desc(), EssayRow.id)
        )
        return [await self._essay(r) for r in rows]

    async def get(self, essay_id: UUID) -> Essay | None:
        """Return one essay."""
        row = await self._s.get(EssayRow, essay_id)
        return await self._essay(row) if row else None

    async def add(self, essay: Essay) -> Essay:
        """Insert an essay."""
        row = EssayRow(id=essay.id, student_id=essay.student_id, lock_version=0)
        await self._fill(row, essay)
        self._s.add(row)
        await self._s.flush()
        await self._s.refresh(row)
        return await self._essay(row)

    async def update(self, essay: Essay) -> Essay:
        """Store the fields and bump the lock version (compare-and-set)."""
        row = await self._s.get(EssayRow, essay.id, with_for_update=True)
        if row is None:
            raise AdmissionNotFoundError()
        if row.lock_version != essay.lock_version:
            raise AdmissionConflictError()
        await self._fill(row, essay)
        row.lock_version = essay.lock_version + 1
        await self._s.flush()
        await self._s.refresh(row)
        return await self._essay(row)

    async def delete(self, essay_id: UUID) -> None:
        """Delete the essay; versions and ideas cascade."""
        await self._s.execute(delete(EssayRow).where(EssayRow.id == essay_id))

    async def versions(self, essay_id: UUID) -> list[EssayVersion]:
        """Return the versions, newest first."""
        owner = await self._owner(essay_id)
        if owner is None:
            return []
        rows = await self._s.scalars(
            select(EssayVersionRow)
            .where(EssayVersionRow.essay_id == essay_id)
            .order_by(EssayVersionRow.version.desc())
        )
        return [await self._version(owner, r) for r in rows]

    async def version(self, essay_id: UUID, version: int) -> EssayVersion | None:
        """Return one version."""
        owner = await self._owner(essay_id)
        if owner is None:
            return None
        row = await self._s.scalar(
            select(EssayVersionRow).where(
                EssayVersionRow.essay_id == essay_id,
                EssayVersionRow.version == version,
            )
        )
        return await self._version(owner, row) if row else None

    async def add_version(self, version: EssayVersion) -> EssayVersion:
        """Insert a version sealed with the essay owner's key."""
        owner = await self._owner(version.essay_id)
        if owner is None:
            raise AdmissionNotFoundError()
        name, rid = version.name, version.id
        sealed = None if name is None else await self._seal(owner, rid, "name", name)
        row = EssayVersionRow(
            id=version.id,
            essay_id=version.essay_id,
            version=version.version,
            name=sealed,
            body=await self._seal(owner, version.id, "body", version.body),
            created_by=version.created_by,
            source=version.source,
            shared=version.shared,
            word_count=version.word_count,
        )
        self._s.add(row)
        await self._s.flush()
        await self._s.refresh(row)
        return await self._version(owner, row)

    async def set_shared(
        self, essay_id: UUID, version: int, shared: bool
    ) -> EssayVersion | None:
        """Share or unshare one version."""
        owner = await self._owner(essay_id)
        if owner is None:
            return None
        row = await self._s.scalar(
            update(EssayVersionRow)
            .where(
                EssayVersionRow.essay_id == essay_id,
                EssayVersionRow.version == version,
            )
            .values(shared=shared)
            .returning(EssayVersionRow)
        )
        return await self._version(owner, row) if row else None

    async def ideas_for(self, student_id: UUID) -> list[EssayIdea]:
        """Return the ideas board in display order."""
        rows = await self._s.scalars(
            select(EssayIdeaRow)
            .where(EssayIdeaRow.student_id == student_id)
            .order_by(EssayIdeaRow.sort_order, EssayIdeaRow.created_at)
        )
        return [await self._idea(r) for r in rows]

    async def get_idea(self, idea_id: UUID) -> EssayIdea | None:
        """Return one idea."""
        row = await self._s.get(EssayIdeaRow, idea_id)
        return await self._idea(row) if row else None

    async def add_idea(self, idea: EssayIdea) -> EssayIdea:
        """Insert an idea."""
        row = EssayIdeaRow(id=idea.id, student_id=idea.student_id, lock_version=0)
        await self._fill_idea(row, idea)
        self._s.add(row)
        await self._s.flush()
        await self._s.refresh(row)
        return await self._idea(row)

    async def update_idea(self, idea: EssayIdea) -> EssayIdea:
        """Store the idea (compare-and-set)."""
        row = await self._s.get(EssayIdeaRow, idea.id)
        if row is None:
            raise AdmissionNotFoundError()
        if row.lock_version != idea.lock_version:
            raise AdmissionConflictError()
        await self._fill_idea(row, idea)
        row.lock_version = idea.lock_version + 1
        await self._s.flush()
        await self._s.refresh(row)
        return await self._idea(row)

    async def delete_idea(self, idea_id: UUID) -> None:
        """Delete an idea."""
        await self._s.execute(delete(EssayIdeaRow).where(EssayIdeaRow.id == idea_id))
