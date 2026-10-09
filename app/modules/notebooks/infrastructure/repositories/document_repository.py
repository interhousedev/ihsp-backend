"""SQL repository of the shared content layer."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from app.modules.notebooks.domain.entities import (
    Document,
    DraftPassage,
    SourceGuide,
)
from app.modules.notebooks.domain.passage_hash import passage_hash
from app.modules.notebooks.infrastructure.orm.document import Document as DocumentRow
from app.modules.notebooks.infrastructure.orm.document import DocumentAlias as AliasRow
from app.modules.notebooks.infrastructure.orm.document import DocumentGuide as GuideRow
from app.modules.notebooks.infrastructure.orm.passage import Passage as PassageRow
from app.modules.notebooks.infrastructure.orm.source import Source as SourceRow
from app.shared.ids import new_id

from sqlalchemy import CursorResult, delete, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession


def _to_entity(row: DocumentRow) -> Document:
    return Document(
        id=row.id,
        content_hash=row.content_hash.strip(),
        word_count=int(row.word_count),
        char_count=int(row.char_count),
        token_estimate=int(row.token_estimate),
        passage_count=int(row.passage_count),
    )


class SqlDocumentRepository:
    """Documents, aliases and guides in the `notebooks` schema."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the unit of work's session."""
        self.session = session

    async def find_by_hash(self, content_hash: str) -> Document | None:
        """The document of a normalized text, if one was stored."""
        stmt = select(DocumentRow).where(DocumentRow.content_hash == content_hash)
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _to_entity(row)

    async def find_by_alias(self, alias: str) -> Document | None:
        """The document a file (checksum or id) turned into, if known."""
        stmt = (
            select(DocumentRow)
            .join(AliasRow, AliasRow.document_id == DocumentRow.id)
            .where(AliasRow.alias == alias)
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _to_entity(row)

    async def add_aliases(self, aliases: Sequence[str], document_id: UUID) -> None:
        """Remember identities of the text; an alias that exists is left alone."""
        if not aliases:
            return
        stmt = pg_insert(AliasRow).values(
            [{"alias": a, "document_id": document_id} for a in dict.fromkeys(aliases)]
        )
        await self.session.execute(stmt.on_conflict_do_nothing())

    async def create(
        self,
        content_hash: str,
        passages: Sequence[DraftPassage],
        *,
        word_count: int,
        char_count: int,
        token_estimate: int,
    ) -> Document:
        """Store a document with its passages, or return the one that exists."""
        document_id = new_id()
        stmt = (
            pg_insert(DocumentRow)
            .values(
                id=document_id,
                content_hash=content_hash,
                word_count=word_count,
                char_count=char_count,
                token_estimate=token_estimate,
                passage_count=len(passages),
            )
            .on_conflict_do_nothing(index_elements=[DocumentRow.content_hash])
            .returning(DocumentRow.id)
        )
        inserted = (await self.session.execute(stmt)).scalar_one_or_none()
        if inserted is None:  # another transaction stored the same text first
            existing = await self.find_by_hash(content_hash)
            assert existing is not None
            return existing
        if passages:
            await self.session.execute(
                insert(PassageRow),
                [
                    {
                        "id": new_id(),
                        "document_id": document_id,
                        "seq": p.seq,
                        "text": p.text,
                        "char_start": p.char_start,
                        "char_end": p.char_end,
                        "token_estimate": p.token_estimate,
                        "page": p.page,
                        "heading": p.heading,
                        "content_hash": passage_hash(p.text),
                    }
                    for p in passages
                ],
            )
        return Document(
            id=document_id,
            content_hash=content_hash,
            word_count=word_count,
            char_count=char_count,
            token_estimate=token_estimate,
            passage_count=len(passages),
        )

    async def get_guide(self, document_id: UUID, language: str) -> SourceGuide | None:
        """The guide of the document in a language, if one was written."""
        stmt = select(GuideRow.guide).where(
            GuideRow.document_id == document_id, GuideRow.language == language
        )
        raw = (await self.session.execute(stmt)).scalar_one_or_none()
        return None if raw is None else SourceGuide.model_validate(raw)

    async def save_guide(
        self, document_id: UUID, language: str, guide: SourceGuide
    ) -> None:
        """Keep the guide (the first one written for a language wins)."""
        stmt = (
            pg_insert(GuideRow)
            .values(
                document_id=document_id,
                language=language,
                guide=guide.model_dump(mode="json"),
            )
            .on_conflict_do_nothing()
        )
        await self.session.execute(stmt)

    async def delete_unused(self, created_before: datetime, limit: int) -> int:
        """Delete documents created before the cutoff that no source points at."""
        used = select(SourceRow.document_id).where(SourceRow.document_id.is_not(None))
        doomed = (
            select(DocumentRow.id)
            .where(DocumentRow.created_at < created_before, DocumentRow.id.not_in(used))
            .order_by(DocumentRow.created_at, DocumentRow.id)
            .limit(limit)
        )
        result = await self.session.execute(
            delete(DocumentRow).where(DocumentRow.id.in_(doomed)),
            execution_options={"synchronize_session": False},
        )
        return int(cast("CursorResult[Any]", result).rowcount)
