"""Sharing rows in the `notebooks` schema."""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from app.modules.notebooks.domain.sharing import LinkedSet, NotebookShare, ShareVia
from app.modules.notebooks.infrastructure.orm.share import (
    NotebookLinkedSetRow,
    NotebookShareLinkRow,
    NotebookShareRow,
)

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession


def _share(row: NotebookShareRow) -> NotebookShare:
    return NotebookShare(
        row.notebook_id, row.user_id, ShareVia(row.via), row.created_at, row.revoked_at
    )


class SqlShareRepository:
    """Grants, links and attached sets of notebooks."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the unit of work's session."""
        self.session = session

    async def find(self, notebook_id: UUID, user_id: UUID) -> NotebookShare | None:
        """The person's row, revoked or not."""
        stmt = (
            select(NotebookShareRow)
            .where(
                NotebookShareRow.notebook_id == notebook_id,
                NotebookShareRow.user_id == user_id,
            )
            .execution_options(populate_existing=True)
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _share(row)

    async def active(self, notebook_id: UUID, user_id: UUID) -> NotebookShare | None:
        """The person's grant unless it was revoked."""
        found = await self.find(notebook_id, user_id)
        return None if found is None or found.revoked_at is not None else found

    async def put(self, share: NotebookShare) -> None:
        """Insert the grant or replace the person's row."""
        values = {
            "via": share.via.value,
            "created_at": share.created_at,
            "updated_at": func.now(),
            "revoked_at": share.revoked_at,
        }
        stmt = insert(NotebookShareRow).values(
            notebook_id=share.notebook_id, user_id=share.user_id, **values
        )
        await self.session.execute(
            stmt.on_conflict_do_update(
                index_elements=[NotebookShareRow.notebook_id, NotebookShareRow.user_id],
                set_=values,
            )
        )

    async def revoke(self, notebook_id: UUID, user_id: UUID, now: datetime) -> bool:
        """Mark a live grant revoked; False when there was none."""
        stmt = (
            update(NotebookShareRow)
            .where(
                NotebookShareRow.notebook_id == notebook_id,
                NotebookShareRow.user_id == user_id,
                NotebookShareRow.revoked_at.is_(None),
            )
            .values(revoked_at=now)
            .returning(NotebookShareRow.user_id)
            .execution_options(synchronize_session=False)
        )
        return (await self.session.execute(stmt)).first() is not None

    async def delete(self, notebook_id: UUID, user_id: UUID) -> None:
        """Forget the person's row."""
        await self.session.execute(
            delete(NotebookShareRow)
            .where(
                NotebookShareRow.notebook_id == notebook_id,
                NotebookShareRow.user_id == user_id,
            )
            .execution_options(synchronize_session=False)
        )

    async def delete_via(self, notebook_id: UUID, via: ShareVia) -> list[UUID]:
        """Forget the live grants of one kind; return who lost access."""
        stmt = (
            delete(NotebookShareRow)
            .where(
                NotebookShareRow.notebook_id == notebook_id,
                NotebookShareRow.via == via.value,
                NotebookShareRow.revoked_at.is_(None),
            )
            .returning(NotebookShareRow.user_id)
            .execution_options(synchronize_session=False)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_active(self, notebook_id: UUID) -> list[NotebookShare]:
        """The live grants of a notebook, oldest first."""
        stmt = (
            select(NotebookShareRow)
            .where(
                NotebookShareRow.notebook_id == notebook_id,
                NotebookShareRow.revoked_at.is_(None),
            )
            .order_by(NotebookShareRow.created_at, NotebookShareRow.user_id)
            .execution_options(populate_existing=True)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [_share(row) for row in rows]

    async def notebooks_of(self, user_id: UUID) -> list[UUID]:
        """Notebooks shared with the person, newest grant first."""
        stmt = (
            select(NotebookShareRow.notebook_id)
            .where(
                NotebookShareRow.user_id == user_id,
                NotebookShareRow.revoked_at.is_(None),
            )
            .order_by(NotebookShareRow.created_at.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def delete_for_user(self, user_id: UUID) -> None:
        """Forget every row of a removed account."""
        await self.session.execute(
            delete(NotebookShareRow)
            .where(NotebookShareRow.user_id == user_id)
            .execution_options(synchronize_session=False)
        )

    async def link_exists(self, notebook_id: UUID) -> bool:
        """True when the notebook has an active link."""
        stmt = select(NotebookShareLinkRow.notebook_id).where(
            NotebookShareLinkRow.notebook_id == notebook_id
        )
        return (await self.session.execute(stmt)).first() is not None

    async def set_link(self, notebook_id: UUID, token_hash: str, now: datetime) -> None:
        """Create the link or replace its token."""
        values = {"token_hash": token_hash, "created_at": now, "updated_at": func.now()}
        stmt = insert(NotebookShareLinkRow).values(notebook_id=notebook_id, **values)
        await self.session.execute(
            stmt.on_conflict_do_update(
                index_elements=[NotebookShareLinkRow.notebook_id], set_=values
            )
        )

    async def delete_link(self, notebook_id: UUID) -> None:
        """Turn the link off."""
        await self.session.execute(
            delete(NotebookShareLinkRow)
            .where(NotebookShareLinkRow.notebook_id == notebook_id)
            .execution_options(synchronize_session=False)
        )

    async def notebook_of_token(self, token_hash: str) -> UUID | None:
        """The notebook of an active link."""
        stmt = select(NotebookShareLinkRow.notebook_id).where(
            NotebookShareLinkRow.token_hash == token_hash
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def linked_sets(self, notebook_id: UUID) -> list[LinkedSet]:
        """The sets attached to a notebook, oldest first."""
        stmt = (
            select(NotebookLinkedSetRow)
            .where(NotebookLinkedSetRow.notebook_id == notebook_id)
            .order_by(NotebookLinkedSetRow.created_at)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [
            LinkedSet(row.notebook_id, row.linked_notebook_id, row.created_at)
            for row in rows
        ]

    async def add_linked_set(self, linked: LinkedSet) -> None:
        """Attach a set (attaching it again changes nothing)."""
        stmt = insert(NotebookLinkedSetRow).values(
            notebook_id=linked.notebook_id,
            linked_notebook_id=linked.linked_notebook_id,
            created_at=linked.created_at,
        )
        await self.session.execute(stmt.on_conflict_do_nothing())

    async def remove_linked_set(self, notebook_id: UUID, linked_id: UUID) -> None:
        """Detach a set."""
        await self.remove_linked_sets_of([notebook_id], linked_id)

    async def remove_linked_sets_of(
        self, user_notebooks: Sequence[UUID], linked_id: UUID
    ) -> None:
        """Detach one set from several notebooks."""
        await self.session.execute(
            delete(NotebookLinkedSetRow)
            .where(
                NotebookLinkedSetRow.notebook_id.in_(user_notebooks),
                NotebookLinkedSetRow.linked_notebook_id == linked_id,
            )
            .execution_options(synchronize_session=False)
        )
