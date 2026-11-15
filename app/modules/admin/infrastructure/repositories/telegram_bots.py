"""SQL repository of the Telegram bot registry and its members."""

from collections.abc import Collection
from datetime import datetime
from uuid import UUID

from app.modules.admin.domain.errors import BotAlreadyExistsError, BotNotFoundError
from app.modules.admin.domain.telegram_bot import (
    BotFeature,
    TelegramBot,
    parse_features,
)
from app.modules.admin.infrastructure.orm.telegram_bot import (
    TelegramBotMemberRow,
    TelegramBotRow,
)

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


def to_entity(row: TelegramBotRow) -> TelegramBot:
    """Map a row; a switch stored under an unknown name is dropped."""
    known = {str(feature) for feature in BotFeature}
    features = parse_features(
        {key: value for key, value in (row.features or {}).items() if key in known}
    )
    return TelegramBot(
        id=row.id,
        name=row.name,
        username=row.username,
        telegram_id=row.telegram_id,
        token_hint=row.token_hint,
        enabled=row.enabled,
        is_default=row.is_default,
        created_at=row.created_at,
        updated_at=row.updated_at,
        features=features,
    )


def _features(bot: TelegramBot) -> dict[str, bool]:
    return {str(key): value for key, value in bot.features.items()}


class SqlBotRepository:
    """Implements `BotRepository` over one session."""

    def __init__(self, session: AsyncSession) -> None:
        """Keep the session."""
        self.session = session

    async def list_all(self) -> list[TelegramBot]:
        """Every bot, the default first."""
        rows = await self.session.scalars(
            select(TelegramBotRow).order_by(
                TelegramBotRow.is_default.desc(), TelegramBotRow.created_at
            )
        )
        return [to_entity(row) for row in rows]

    async def get(self, bot_id: UUID, *, for_update: bool = False) -> TelegramBot:
        """One bot or BotNotFoundError."""
        query = select(TelegramBotRow).where(TelegramBotRow.id == bot_id)
        if for_update:
            query = query.with_for_update()
        row = await self.session.scalar(query)
        if row is None:
            raise BotNotFoundError(support_details=str(bot_id))
        return to_entity(row)

    async def by_telegram_id(self, telegram_id: int) -> TelegramBot | None:
        """The bot with this Telegram id."""
        row = await self.session.scalar(
            select(TelegramBotRow).where(TelegramBotRow.telegram_id == telegram_id)
        )
        return None if row is None else to_entity(row)

    async def add(self, bot: TelegramBot, *, actor_id: UUID | None) -> None:
        """Insert; the timestamps come from the database."""
        row = TelegramBotRow(
            id=bot.id,
            name=bot.name,
            username=bot.username,
            telegram_id=bot.telegram_id,
            token_hint=bot.token_hint,
            enabled=bot.enabled,
            is_default=bot.is_default,
            features=_features(bot),
            created_by=actor_id,
            updated_by=actor_id,
        )
        self.session.add(row)
        try:
            await self.session.flush()
        except IntegrityError as exc:  # same Telegram id or a second default
            raise BotAlreadyExistsError(
                support_details=f"telegram id {bot.telegram_id}"
            ) from exc
        await self.session.refresh(row)
        bot.created_at, bot.updated_at = row.created_at, row.updated_at

    async def save(self, bot: TelegramBot, *, actor_id: UUID | None) -> None:
        """Write the mutable fields back."""
        row = await self.session.get(TelegramBotRow, bot.id)
        if row is None:
            raise BotNotFoundError(support_details=str(bot.id))
        row.name = bot.name
        row.username = bot.username
        row.telegram_id = bot.telegram_id
        row.token_hint = bot.token_hint
        row.enabled = bot.enabled
        row.features = _features(bot)
        row.updated_by = actor_id
        await self.session.flush()
        await self.session.refresh(row)
        bot.updated_at = row.updated_at

    async def members(self, bot_id: UUID, user_ids: Collection[UUID]) -> set[UUID]:
        """Which of these users wrote to the bot."""
        if not user_ids:
            return set()
        rows = await self.session.scalars(
            select(TelegramBotMemberRow.user_id).where(
                TelegramBotMemberRow.bot_id == bot_id,
                TelegramBotMemberRow.user_id.in_(list(user_ids)),
            )
        )
        return {user_id for user_id in rows if user_id is not None}

    async def member_counts(self) -> dict[UUID, int]:
        """Linked users per bot."""
        rows = await self.session.execute(
            select(
                TelegramBotMemberRow.bot_id,
                func.count(func.distinct(TelegramBotMemberRow.user_id)),
            ).group_by(TelegramBotMemberRow.bot_id)
        )
        return {row[0]: int(row[1]) for row in rows.all()}


async def touch_member(
    session: AsyncSession,
    *,
    bot_id: UUID,
    telegram_user_id: int,
    user_id: UUID | None,
    seen_at: datetime,
) -> None:
    """Record that a Telegram user wrote to a bot (the caller commits)."""
    statement = insert(TelegramBotMemberRow).values(
        bot_id=bot_id,
        telegram_user_id=telegram_user_id,
        user_id=user_id,
        last_seen_at=seen_at,
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[
                TelegramBotMemberRow.bot_id,
                TelegramBotMemberRow.telegram_user_id,
            ],
            set_={"user_id": user_id, "last_seen_at": seen_at},
        )
    )
