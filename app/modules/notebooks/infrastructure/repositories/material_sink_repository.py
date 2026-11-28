"""Subject notebook lookup and text source writer for the material sink."""

from typing import Any
from uuid import UUID

from app.modules.notebooks.domain.entities import AutoSettings
from app.modules.notebooks.infrastructure.orm.notebook import Notebook
from app.modules.notebooks.infrastructure.orm.source import Source
from app.shared.ids import new_id

from pydantic_core import to_jsonable_python
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


class SqlNotebookDirectory:
    """Finds or creates the teacher's subject (and group) notebook."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the directory to a session."""
        self.session = session

    async def subject_notebook(
        self, owner_id: UUID, subject_id: UUID, group_id: UUID | None
    ) -> UUID:
        """The live notebook of the subject, created when missing."""
        stmt = select(Notebook.id).where(
            Notebook.owner_id == owner_id,
            Notebook.subject_id == subject_id,
            Notebook.origin == "subject_auto",
            Notebook.deleted_at.is_(None),
            (
                Notebook.group_id.is_(None)
                if group_id is None
                else Notebook.group_id == group_id
            ),
        )
        found = (await self.session.execute(stmt)).scalar_one_or_none()
        if found is not None:
            return found
        row = Notebook(
            id=new_id(),
            owner_id=owner_id,
            title="Materials",
            origin="subject_auto",
            subject_id=subject_id,
            group_id=group_id,
            auto_settings=AutoSettings().model_dump(mode="json"),
        )
        self.session.add(row)
        await self.session.flush()
        return row.id


class SqlSourceWriter:
    """Adds text sources, once per (notebook, ref_key)."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the writer to a session."""
        self.session = session

    async def add_text(
        self,
        *,
        notebook_id: UUID,
        owner_id: UUID,
        title: str,
        body_md: str,
        ref: dict[str, Any],
        ref_key: str,
        origin: dict[str, Any],
    ) -> Source:
        """Add the source, or return the one stored under the same key."""
        found = (
            await self.session.execute(
                select(Source).where(
                    Source.notebook_id == notebook_id, Source.ref_key == ref_key
                )
            )
        ).scalar_one_or_none()
        if found is not None:
            return found
        position = (
            await self.session.execute(
                select(func.coalesce(func.max(Source.position), -1) + 1).where(
                    Source.notebook_id == notebook_id
                )
            )
        ).scalar_one()
        row = Source(
            id=new_id(),
            notebook_id=notebook_id,
            owner_id=owner_id,
            kind="text",
            title=title,
            ref=to_jsonable_python(ref),
            ref_key=ref_key,
            origin=to_jsonable_python(origin),
            position=position,
            status="pending",
            body_md=body_md,
        )
        self.session.add(row)
        await self.session.flush()
        return row
