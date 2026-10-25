"""SQL repositories of the posts module."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.modules.posts.domain.bot_mode import BotMode
from app.modules.posts.domain.errors import SlugTakenError
from app.modules.posts.domain.post import Audience, Post, UrlButton
from app.modules.posts.infrastructure.orm import BotUserModeRow, PostRow

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from uuid_utils.compat import uuid7


def _to_domain(row: PostRow) -> Post:
    buttons: list[Any] = row.buttons or []
    return Post(
        id=row.id,
        parent_id=row.parent_id,
        slug=row.slug,
        title=dict(row.title or {}),
        body=dict(row.body or {}),
        audience=Audience(row.audience),
        sort_order=row.sort_order,
        published=row.published,
        is_root=row.is_root,
        buttons=tuple(UrlButton(dict(b["label"]), str(b["url"])) for b in buttons),
    )


def _apply(row: PostRow, post: Post) -> None:
    row.parent_id = post.parent_id
    row.slug = post.slug
    row.title = dict(post.title)
    row.body = dict(post.body)
    row.audience = post.audience.value
    row.sort_order = post.sort_order
    row.published = post.published
    row.is_root = post.is_root
    row.buttons = [{"label": dict(b.label), "url": b.url} for b in post.buttons]


class SqlPostRepository:
    """`PostRepository` over posts.posts."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Store the session factory."""
        self.sessionmaker = sessionmaker

    async def list_all(self) -> list[Post]:
        """Every post."""
        async with self.sessionmaker() as session:
            rows = (await session.scalars(select(PostRow))).all()
        return [_to_domain(row) for row in rows]

    async def add(self, post: Post) -> None:
        """Insert a post."""
        row = PostRow(id=post.id)
        _apply(row, post)
        async with self.sessionmaker() as session:
            session.add(row)
            await self._commit(session)

    async def save_many(self, posts: Sequence[Post]) -> None:
        """Update posts in one transaction."""
        async with self.sessionmaker() as session:
            for post in posts:
                row = await session.get(PostRow, post.id)
                if row is not None:
                    _apply(row, post)
            await self._commit(session)

    async def delete_many(self, ids: Sequence[UUID]) -> None:
        """Delete posts in one transaction."""
        async with self.sessionmaker() as session:
            await session.execute(delete(PostRow).where(PostRow.id.in_(list(ids))))
            await session.commit()

    @staticmethod
    async def _commit(session: AsyncSession) -> None:
        try:
            await session.commit()
        except IntegrityError as error:
            await session.rollback()
            raise SlugTakenError(support_details=str(error.orig)) from error


class SqlBotModeRepository:
    """`BotModeRepository` over posts.bot_user_modes."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Store the session factory."""
        self.sessionmaker = sessionmaker

    async def get(self, telegram_user_id: int) -> BotMode | None:
        """The stored choice."""
        async with self.sessionmaker() as session:
            mode = await session.scalar(
                select(BotUserModeRow.mode).where(
                    BotUserModeRow.telegram_user_id == telegram_user_id
                )
            )
        return BotMode(mode) if mode else None

    async def set(self, telegram_user_id: int, mode: BotMode) -> None:
        """Upsert the choice."""
        statement = insert(BotUserModeRow).values(
            id=uuid7(), telegram_user_id=telegram_user_id, mode=mode.value
        )
        statement = statement.on_conflict_do_update(
            index_elements=[BotUserModeRow.telegram_user_id],
            set_={"mode": mode.value, "updated_at": func.now()},
        )
        async with self.sessionmaker() as session:
            await session.execute(statement)
            await session.commit()
