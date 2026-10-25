"""SQLAlchemy repository of Telegram links (id.telegram_links)."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.identity.domain.telegram_link import TelegramLink
from app.modules.identity.infrastructure.orm import TelegramLink as LinkRow
from app.shared.ids import new_id

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession


def _to_entity(row: LinkRow) -> TelegramLink:
    return TelegramLink(
        telegram_user_id=row.telegram_user_id,
        user_id=row.user_id,
        first_name=row.first_name,
        otp_delivery=row.otp_delivery,
        username=row.username,
        blocked_at=row.blocked_at,
        last_seen_at=row.last_seen_at,
        linked_at=row.linked_at,
    )


def _apply(row: LinkRow, link: TelegramLink) -> None:
    row.user_id = link.user_id
    row.first_name = link.first_name
    row.otp_delivery = link.otp_delivery
    row.username = link.username
    row.blocked_at = link.blocked_at
    if link.last_seen_at is not None:
        row.last_seen_at = link.last_seen_at
    if link.linked_at is not None:
        row.linked_at = link.linked_at


class SqlTelegramLinkRepository:
    """TelegramLinkRepository over an open AsyncSession."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the unit of work's session."""
        self._session = session

    async def _row(self, telegram_user_id: int) -> LinkRow | None:
        row: LinkRow | None = await self._session.scalar(
            select(LinkRow).where(LinkRow.telegram_user_id == telegram_user_id)
        )
        return row

    async def get(self, telegram_user_id: int) -> TelegramLink | None:
        """Return the link of a Telegram account."""
        row = await self._row(telegram_user_id)
        return _to_entity(row) if row else None

    async def list_for_user(self, user_id: UUID) -> list[TelegramLink]:
        """Links of a user, oldest first."""
        rows = await self._session.scalars(
            select(LinkRow).where(LinkRow.user_id == user_id).order_by(LinkRow.id)
        )
        return [_to_entity(row) for row in rows]

    async def list_for_users(
        self, user_ids: Sequence[UUID]
    ) -> dict[UUID, list[TelegramLink]]:
        """Links of several users."""
        result: dict[UUID, list[TelegramLink]] = {uid: [] for uid in user_ids}
        if not user_ids:
            return result
        rows = await self._session.scalars(
            select(LinkRow)
            .where(LinkRow.user_id.in_(list(user_ids)))
            .order_by(LinkRow.id)
        )
        for row in rows:
            result[row.user_id].append(_to_entity(row))
        return result

    async def add(self, link: TelegramLink) -> None:
        """Insert a link."""
        row = LinkRow(id=new_id(), telegram_user_id=link.telegram_user_id)
        _apply(row, link)
        self._session.add(row)
        await self._session.flush()

    async def save(self, link: TelegramLink) -> None:
        """Write every field of an existing link."""
        row = await self._row(link.telegram_user_id)
        if row is None:
            raise LookupError(f"telegram link {link.telegram_user_id} does not exist")
        _apply(row, link)
        await self._session.flush()

    async def delete(self, telegram_user_id: int) -> bool:
        """Delete a link; True if it existed."""
        result = await self._session.execute(
            delete(LinkRow).where(LinkRow.telegram_user_id == telegram_user_id)
        )
        return bool(result.rowcount)  # type: ignore[attr-defined]

    async def delete_all_for_user(self, user_id: UUID) -> list[TelegramLink]:
        """Delete every link of a user and return them."""
        rows = await self._session.scalars(
            delete(LinkRow)
            .where(LinkRow.user_id == user_id)
            .returning(LinkRow)
            .execution_options(populate_existing=True)
        )
        return [_to_entity(row) for row in rows]
