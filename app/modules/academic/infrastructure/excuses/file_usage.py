"""Which excuses a stored file is attached to (files 'used by' and safe delete)."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.academic.infrastructure.classwork.sql_helpers import uuid_array
from app.modules.academic.infrastructure.orm.excuse import (
    Excuse,
    ExcuseMessage,
    ExcuseTemplate,
)

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class SqlExcuseFileUsage:
    """Answers ``used_by_files`` from the thread messages' attachments."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Store the session factory."""
        self.sessionmaker = sessionmaker

    async def used_by_files(
        self, file_ids: Sequence[UUID]
    ) -> dict[UUID, list[tuple[str, UUID, str]]]:
        """Return ``("excuse", excuse_id, template_code)`` per attached file."""
        if not file_ids:
            return {}
        wanted = set(file_ids)
        async with self.sessionmaker() as session:
            rows = (
                await session.execute(
                    select(ExcuseMessage.file_ids, Excuse.id, ExcuseTemplate.code)
                    .join(Excuse, Excuse.id == ExcuseMessage.excuse_id)
                    .join(ExcuseTemplate, ExcuseTemplate.id == Excuse.template_id)
                    .where(
                        ExcuseMessage.file_ids.op("&&", is_comparison=True)(
                            uuid_array(list(wanted))
                        )
                    )
                )
            ).all()
        used: dict[UUID, list[tuple[str, UUID, str]]] = {}
        for attached, excuse_id, code in rows:
            for file_id in wanted.intersection(attached):
                entry = ("excuse", excuse_id, code)
                places = used.setdefault(file_id, [])
                if entry not in places:
                    places.append(entry)
        return used
