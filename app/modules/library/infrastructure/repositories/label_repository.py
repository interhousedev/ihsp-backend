"""SQL repository of authors and tags: get-or-create, fuzzy search, item links."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.modules.library.domain.catalogue_labels import (
    Author,
    Tag,
    TagCount,
    distinct_authors,
    distinct_tags,
)
from app.modules.library.domain.enums import ItemStatus
from app.modules.library.domain.name_keys import name_key
from app.modules.library.infrastructure.orm import Author as AuthorRow
from app.modules.library.infrastructure.orm import Item as ItemRow
from app.modules.library.infrastructure.orm import ItemAuthor as ItemAuthorRow
from app.modules.library.infrastructure.orm import ItemTag as ItemTagRow
from app.modules.library.infrastructure.orm import Tag as TagRow
from app.shared.ids import new_id

from sqlalchemy import ColumnElement, and_, case, delete, func, literal, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

SIMILAR = 0.45
"""`word_similarity` from which a key counts as a near match (typos, other spelling)."""


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _match(column: ColumnElement[str], key: str) -> ColumnElement[bool]:
    """Every word of the key is contained, or the whole key is trigram-close."""
    words = [w for w in key.split() if w]
    contains = and_(*[column.ilike(f"%{_escape_like(w)}%", escape="\\") for w in words])
    return or_(contains, func.word_similarity(literal(key), column) >= SIMILAR)


def _rank(column: ColumnElement[str], key: str) -> list[ColumnElement[float]]:
    starts = column.ilike(f"{_escape_like(key)}%", escape="\\")
    return [
        case((starts, 0), else_=1),
        -func.word_similarity(literal(key), column),
    ]


class SqlLabelRepository:
    """Stores authors and tags in schema `library`."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the unit of work's session."""
        self.session = session

    # - - - Search - - -

    async def search_authors(self, text: str, *, limit: int) -> list[Author]:
        """Authors whose key contains the text or is close to it, best first."""
        key = name_key(text)
        if not key:
            return []
        rows = await self.session.execute(
            select(AuthorRow)
            .where(_match(AuthorRow.name_key, key))
            .order_by(*_rank(AuthorRow.name_key, key), AuthorRow.name)
            .limit(limit)
        )
        return [Author(r.id, r.name, r.name_key) for r in rows.scalars()]

    async def search_tags(self, text: str, *, limit: int) -> list[TagCount]:
        """Tags matching the text (all when empty) with item counts, best first."""
        key = name_key(text)
        count = (
            select(func.count())
            .select_from(ItemTagRow)
            .join(ItemRow, ItemRow.id == ItemTagRow.item_id)
            .where(
                ItemTagRow.tag_id == TagRow.id,
                ItemRow.status == ItemStatus.PUBLISHED.value,
            )
            .scalar_subquery()
        )
        query = select(TagRow, count.label("item_count"))
        if key:
            query = query.where(_match(TagRow.name_key, key)).order_by(
                *_rank(TagRow.name_key, key), TagRow.name
            )
        else:
            query = query.order_by(count.desc(), TagRow.name)
        rows = await self.session.execute(query.limit(limit))
        return [
            TagCount(Tag(row.id, row.name, row.name_key), int(total))
            for row, total in rows.all()
        ]

    # - - - Get or create - - -

    async def ensure_authors(self, names: Sequence[str]) -> list[Author]:
        """The authors of the names in order; unknown ones are created."""
        pairs = distinct_authors(names)
        found = await self._ensure(AuthorRow, pairs)
        return [Author(r.id, r.name, r.name_key) for r in found]

    async def ensure_tags(self, names: Sequence[str]) -> list[Tag]:
        """The tags of the names in order; unknown ones are created."""
        pairs = distinct_tags(names)
        found = await self._ensure(TagRow, pairs)
        return [Tag(r.id, r.name, r.name_key) for r in found]

    async def _ensure(self, model: Any, pairs: list[tuple[str, str]]) -> list[Any]:
        if not pairs:
            return []
        keys = [key for _, key in pairs]
        statement = pg_insert(model).values(
            [{"id": new_id(), "name": name, "name_key": key} for name, key in pairs]
        )
        await self.session.execute(
            statement.on_conflict_do_nothing(index_elements=["name_key"])
        )
        rows = await self.session.execute(select(model).where(model.name_key.in_(keys)))
        by_key = {r.name_key: r for r in rows.scalars()}
        return [by_key[key] for key in keys]

    # - - - Item links - - -

    async def set_item_authors(self, item_id: UUID, names: Sequence[str]) -> None:
        """Replace the author links of the item, creating authors that are new."""
        authors = await self.ensure_authors(names)
        await self.session.execute(
            delete(ItemAuthorRow).where(ItemAuthorRow.item_id == item_id)
        )
        for position, author in enumerate(authors):
            self.session.add(
                ItemAuthorRow(item_id=item_id, author_id=author.id, position=position)
            )
        await self.session.flush()

    async def set_item_tags(self, item_id: UUID, names: Sequence[str]) -> None:
        """Replace the tag links of the item, creating tags that are new."""
        tags = await self.ensure_tags(names)
        await self.session.execute(
            delete(ItemTagRow).where(ItemTagRow.item_id == item_id)
        )
        for tag in tags:
            self.session.add(ItemTagRow(item_id=item_id, tag_id=tag.id))
        await self.session.flush()

    async def item_tags(self, item_ids: Sequence[UUID]) -> dict[UUID, list[str]]:
        """Tag names of each item, alphabetically (items without tags are absent)."""
        result: dict[UUID, list[str]] = {}
        if not item_ids:
            return result
        rows = await self.session.execute(
            select(ItemTagRow.item_id, TagRow.name)
            .join(TagRow, TagRow.id == ItemTagRow.tag_id)
            .where(ItemTagRow.item_id.in_(set(item_ids)))
            .order_by(func.lower(TagRow.name))
        )
        for item_id, name in rows.all():
            result.setdefault(item_id, []).append(name)
        return result
