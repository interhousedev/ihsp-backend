"""Sharing rows in the `files` schema."""

from datetime import datetime
from uuid import UUID

from app.modules.files.domain.sharing import FileShare, FileShareVia
from app.modules.files.infrastructure.orm.share import FileShareLinkRow, FileShareRow

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession


def _share(row: FileShareRow) -> FileShare:
    return FileShare(
        row.file_id, row.user_id, FileShareVia(row.via), row.created_at, row.revoked_at
    )


class SqlFileShareRepository:
    """Grants and links of files."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the unit of work's session."""
        self.session = session

    async def find(self, file_id: UUID, user_id: UUID) -> FileShare | None:
        """The person's row, revoked or not."""
        stmt = (
            select(FileShareRow)
            .where(FileShareRow.file_id == file_id, FileShareRow.user_id == user_id)
            .execution_options(populate_existing=True)
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _share(row)

    async def put(self, share: FileShare) -> None:
        """Insert the grant or replace the person's row."""
        values = {
            "via": share.via.value,
            "created_at": share.created_at,
            "updated_at": func.now(),
            "revoked_at": share.revoked_at,
        }
        stmt = insert(FileShareRow).values(
            file_id=share.file_id, user_id=share.user_id, **values
        )
        await self.session.execute(
            stmt.on_conflict_do_update(
                index_elements=[FileShareRow.file_id, FileShareRow.user_id], set_=values
            )
        )

    async def delete(self, file_id: UUID, user_id: UUID) -> None:
        """Forget the person's row."""
        await self.session.execute(
            delete(FileShareRow)
            .where(FileShareRow.file_id == file_id, FileShareRow.user_id == user_id)
            .execution_options(synchronize_session=False)
        )

    async def delete_via(self, file_id: UUID, via: FileShareVia) -> None:
        """Forget the live grants of one kind."""
        await self.session.execute(
            delete(FileShareRow)
            .where(
                FileShareRow.file_id == file_id,
                FileShareRow.via == via.value,
                FileShareRow.revoked_at.is_(None),
            )
            .execution_options(synchronize_session=False)
        )

    async def list_active(self, file_id: UUID) -> list[FileShare]:
        """The live grants of a file, oldest first."""
        stmt = (
            select(FileShareRow)
            .where(FileShareRow.file_id == file_id, FileShareRow.revoked_at.is_(None))
            .order_by(FileShareRow.created_at, FileShareRow.user_id)
            .execution_options(populate_existing=True)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [_share(row) for row in rows]

    async def files_of(self, user_id: UUID) -> list[UUID]:
        """Files shared with the person, newest grant first."""
        stmt = (
            select(FileShareRow.file_id)
            .where(FileShareRow.user_id == user_id, FileShareRow.revoked_at.is_(None))
            .order_by(FileShareRow.created_at.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def delete_for_user(self, user_id: UUID) -> None:
        """Forget every row of a removed account."""
        await self.session.execute(
            delete(FileShareRow)
            .where(FileShareRow.user_id == user_id)
            .execution_options(synchronize_session=False)
        )

    async def link_exists(self, file_id: UUID) -> bool:
        """True when the file has an active link."""
        stmt = select(FileShareLinkRow.file_id).where(
            FileShareLinkRow.file_id == file_id
        )
        return (await self.session.execute(stmt)).first() is not None

    async def set_link(self, file_id: UUID, token_hash: str, now: datetime) -> None:
        """Create the link or replace its token."""
        values = {"token_hash": token_hash, "created_at": now, "updated_at": func.now()}
        stmt = insert(FileShareLinkRow).values(file_id=file_id, **values)
        await self.session.execute(
            stmt.on_conflict_do_update(
                index_elements=[FileShareLinkRow.file_id], set_=values
            )
        )

    async def delete_link(self, file_id: UUID) -> None:
        """Turn the link off."""
        await self.session.execute(
            delete(FileShareLinkRow)
            .where(FileShareLinkRow.file_id == file_id)
            .execution_options(synchronize_session=False)
        )

    async def file_of_token(self, token_hash: str) -> UUID | None:
        """The file of an active link."""
        stmt = select(FileShareLinkRow.file_id).where(
            FileShareLinkRow.token_hash == token_hash
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()
