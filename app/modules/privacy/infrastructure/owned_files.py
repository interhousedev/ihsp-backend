"""The user's own uploaded files, read from ``files.files``."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.files.infrastructure.orm.file import File
from app.modules.privacy.ports.gateways import OwnedFile

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class SqlOwnedFiles:
    """Ready files of one owner."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Store the session factory."""
        self._sessionmaker = sessionmaker

    async def list_of(self, user_id: UUID) -> Sequence[OwnedFile]:
        """The user's ready files, oldest first."""
        async with self._sessionmaker() as session:
            rows = await session.execute(
                select(File.key, File.name, File.byte_size)
                .where(File.owner_id == user_id, File.status == "ready")
                .order_by(File.created_at, File.id)
            )
            return [OwnedFile(k, n, s) for k, n, s in rows.all()]
