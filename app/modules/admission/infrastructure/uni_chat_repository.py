"""SQL storage of the university chats; each call opens and commits a session."""

import datetime as dt
from typing import Any
from uuid import UUID

from app.modules.admission.domain.uni_chat import CachedWeb, UniChatLink
from app.modules.admission.infrastructure.orm.uni_chat import (
    UniChatRow,
    UniDefaultPromptRow,
    UniWebCacheRow,
)
from app.shared.ids import new_id

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _link(row: UniChatRow) -> UniChatLink:
    return UniChatLink(
        id=row.id,
        student_id=row.student_id,
        institution_id=row.institution_id,
        chat_id=row.chat_id,
        auto_run_pending=row.auto_run_pending,
        created_at=row.created_at,
        auto_ran_at=row.auto_ran_at,
    )


class SqlUniChatRepository:
    """Links, default prompts and the 14-day web cache in Postgres."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Keep the sessionmaker."""
        self._sm = sessionmaker

    async def link(self, student_id: UUID, institution_id: UUID) -> UniChatLink | None:
        """Return the student's link to a university chat."""
        async with self._sm() as session:
            row = await session.scalar(
                select(UniChatRow).where(
                    UniChatRow.student_id == student_id,
                    UniChatRow.institution_id == institution_id,
                )
            )
        return _link(row) if row else None

    async def link_by_chat(self, chat_id: UUID) -> UniChatLink | None:
        """Return the link of an AI chat."""
        async with self._sm() as session:
            row = await session.scalar(
                select(UniChatRow).where(UniChatRow.chat_id == chat_id)
            )
        return _link(row) if row else None

    async def add(self, link: UniChatLink) -> UniChatLink:
        """Insert a link; a concurrent insert wins and is returned."""
        async with self._sm() as session, session.begin():
            await session.execute(
                insert(UniChatRow)
                .values(
                    id=link.id,
                    student_id=link.student_id,
                    institution_id=link.institution_id,
                    chat_id=link.chat_id,
                    auto_run_pending=link.auto_run_pending,
                    created_at=link.created_at,
                )
                .on_conflict_do_nothing(index_elements=["student_id", "institution_id"])
            )
        found = await self.link(link.student_id, link.institution_id)
        return found or link

    async def relink(self, link: UniChatLink, old_chat_id: UUID) -> bool:
        """Point the link at a new chat unless a concurrent open did first."""
        async with self._sm() as session, session.begin():
            moved = await session.scalar(
                update(UniChatRow)
                .where(UniChatRow.id == link.id, UniChatRow.chat_id == old_chat_id)
                .values(chat_id=link.chat_id, auto_run_pending=link.auto_run_pending)
                .returning(UniChatRow.id)
            )
        return moved is not None

    async def claim_auto_run(self, link_id: UUID, now: dt.datetime) -> bool:
        """Record the one auto run; only the first caller sees True."""
        async with self._sm() as session, session.begin():
            claimed = await session.scalar(
                update(UniChatRow)
                .where(UniChatRow.id == link_id, UniChatRow.auto_ran_at.is_(None))
                .values(auto_run_pending=False, auto_ran_at=now)
                .returning(UniChatRow.id)
            )
        return claimed is not None

    async def prompt(self, student_id: UUID) -> str | None:
        """Return the default prompt."""
        async with self._sm() as session:
            row = await session.get(UniDefaultPromptRow, student_id)
        return row.prompt if row else None

    async def set_prompt(self, student_id: UUID, text: str, now: dt.datetime) -> None:
        """Upsert the prompt; "" deletes it."""
        async with self._sm() as session, session.begin():
            if not text:
                await session.execute(
                    delete(UniDefaultPromptRow).where(
                        UniDefaultPromptRow.student_id == student_id
                    )
                )
                return
            stmt = insert(UniDefaultPromptRow).values(
                student_id=student_id, prompt=text, created_at=now, updated_at=now
            )
            await session.execute(
                stmt.on_conflict_do_update(
                    index_elements=["student_id"],
                    set_={"prompt": text, "updated_at": now},
                )
            )

    async def cached(self, kind: str, key: str) -> CachedWeb | None:
        """Return a cached web result."""
        async with self._sm() as session:
            row = await session.scalar(
                select(UniWebCacheRow).where(
                    UniWebCacheRow.kind == kind, UniWebCacheRow.cache_key == key
                )
            )
        return CachedWeb(row.payload, row.fetched_at) if row else None

    async def store(
        self, kind: str, key: str, payload: dict[str, Any], now: dt.datetime
    ) -> None:
        """Insert or refresh a cached web result."""
        stmt = insert(UniWebCacheRow).values(
            id=new_id(), kind=kind, cache_key=key, payload=payload, fetched_at=now
        )
        async with self._sm() as session, session.begin():
            await session.execute(
                stmt.on_conflict_do_update(
                    index_elements=["kind", "cache_key"],
                    set_={"payload": payload, "fetched_at": now},
                )
            )

    async def erase(self, student_id: UUID) -> None:
        """Delete the student's links and default prompt."""
        async with self._sm() as session, session.begin():
            await session.execute(
                delete(UniChatRow).where(UniChatRow.student_id == student_id)
            )
            await session.execute(
                delete(UniDefaultPromptRow).where(
                    UniDefaultPromptRow.student_id == student_id
                )
            )
