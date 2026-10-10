"""SQL store of the platform settings (one short transaction per call)."""

from typing import Any
from uuid import UUID

from app.modules.admin.infrastructure.orm.platform_setting import PlatformSetting

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql import func


class SqlPlatformSettingsStore:
    """Implements PlatformSettingsStore over the sessionmaker."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Keep the sessionmaker."""
        self.sessionmaker = sessionmaker

    async def read_all(self) -> dict[str, Any]:
        """Return every stored key with its value."""
        async with self.sessionmaker() as session:
            rows = await session.execute(
                select(PlatformSetting.key, PlatformSetting.value)
            )
            return {row[0]: row[1] for row in rows.all()}

    async def write(self, values: dict[str, Any], *, updated_by: UUID) -> None:
        """Upsert the given keys and commit."""
        if not values:
            return
        async with self.sessionmaker() as session:
            statement = insert(PlatformSetting).values(
                [
                    {"key": key, "value": value, "updated_by": updated_by}
                    for key, value in values.items()
                ]
            )
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[PlatformSetting.key],
                    set_={
                        "value": statement.excluded.value,
                        "updated_by": statement.excluded.updated_by,
                        "updated_at": func.now(),
                    },
                )
            )
            await session.commit()
