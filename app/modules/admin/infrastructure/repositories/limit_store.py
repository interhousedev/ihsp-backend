"""SQL store of the runtime limits: overrides and per-user extensions."""

from typing import Any
from uuid import UUID

from app.modules.admin.domain.limits import (
    OVERRIDE_PREFIX,
    ExtensionRecord,
    ExtensionTerms,
)
from app.modules.admin.infrastructure.orm.ai_access import AiAccessRow
from app.modules.admin.infrastructure.orm.limit_extension import LimitExtensionRow
from app.modules.admin.infrastructure.orm.platform_setting import PlatformSetting
from app.shared.ai_access import AiAccess

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func


class SqlLimitStore:
    """Implements `LimitStore` over one session (a unit of work's, or a read's)."""

    def __init__(self, session: AsyncSession) -> None:
        """Keep the session."""
        self.session = session

    async def read_overrides(self) -> dict[str, Any]:
        """Every ``limit.<name>`` row of the platform settings."""
        rows = await self.session.execute(
            select(PlatformSetting.key, PlatformSetting.value).where(
                PlatformSetting.key.like(f"{OVERRIDE_PREFIX}%")
            )
        )
        return {row[0]: row[1] for row in rows.all()}

    async def write_overrides(
        self, upserts: dict[str, int], deletes: list[str], *, updated_by: UUID
    ) -> None:
        """Upsert the given overrides and delete the reset ones."""
        if upserts:
            statement = insert(PlatformSetting).values(
                [
                    {"key": key, "value": value, "updated_by": updated_by}
                    for key, value in upserts.items()
                ]
            )
            await self.session.execute(
                statement.on_conflict_do_update(
                    index_elements=[PlatformSetting.key],
                    set_={
                        "value": statement.excluded.value,
                        "updated_by": statement.excluded.updated_by,
                        "updated_at": func.now(),
                    },
                )
            )
        if deletes:
            await self.session.execute(
                delete(PlatformSetting).where(PlatformSetting.key.in_(deletes))
            )

    async def read_extensions(self) -> list[ExtensionRecord]:
        """Every extension, oldest first."""
        rows = await self.session.execute(
            select(LimitExtensionRow).order_by(LimitExtensionRow.created_at)
        )
        return [_record(row) for row in rows.scalars().all()]

    async def get_extension(self, user_id: UUID) -> ExtensionRecord | None:
        """The extension of one user."""
        row = await self.session.get(LimitExtensionRow, user_id)
        return _record(row) if row is not None else None

    async def save_extension(
        self, user_id: UUID, terms: ExtensionTerms, *, actor_id: UUID
    ) -> None:
        """Insert or replace the extension of a user."""
        row = await self.session.get(LimitExtensionRow, user_id)
        if row is None:
            row = LimitExtensionRow(user_id=user_id, created_by=actor_id)
            self.session.add(row)
        row.multiplier = terms.multiplier
        row.values = dict(terms.values)
        row.expires_on = terms.expires_on
        row.note = terms.note
        row.updated_by = actor_id
        await self.session.flush()

    async def delete_extension(self, user_id: UUID) -> bool:
        """Remove the extension of a user."""
        row = await self.session.get(LimitExtensionRow, user_id)
        if row is None:
            return False
        await self.session.delete(row)
        await self.session.flush()
        return True

    async def read_ai_access(self) -> dict[UUID, AiAccess]:
        """The revoked AI scopes of every user that has a row."""
        rows = await self.session.execute(select(AiAccessRow))
        return {row.user_id: _access(row) for row in rows.scalars().all()}

    async def get_ai_access(self, user_id: UUID) -> AiAccess:
        """The revoked AI scopes of one user."""
        row = await self.session.get(AiAccessRow, user_id)
        return _access(row) if row is not None else AiAccess()

    async def save_ai_access(
        self, user_id: UUID, access: AiAccess, *, actor_id: UUID
    ) -> None:
        """Insert or replace the revoked AI scopes of a user."""
        row = await self.session.get(AiAccessRow, user_id)
        if row is None:
            row = AiAccessRow(user_id=user_id)
            self.session.add(row)
        row.ai_chat_blocked = access.chat_blocked
        row.ai_notebooks_blocked = access.notebooks_blocked
        row.updated_by = actor_id
        await self.session.flush()


def _access(row: AiAccessRow) -> AiAccess:
    return AiAccess(
        chat_blocked=bool(row.ai_chat_blocked),
        notebooks_blocked=bool(row.ai_notebooks_blocked),
    )


def _record(row: LimitExtensionRow) -> ExtensionRecord:
    return ExtensionRecord(
        user_id=row.user_id,
        terms=ExtensionTerms(
            multiplier=row.multiplier,
            values={str(k): int(v) for k, v in (row.values or {}).items()},
            expires_on=row.expires_on,
            note=row.note or "",
        ),
        created_at=row.created_at,
        updated_at=row.updated_at,
        updated_by=row.updated_by,
    )
