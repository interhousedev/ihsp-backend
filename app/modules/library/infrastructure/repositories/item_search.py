"""SQL of the catalogue search: who sees what, filters, ranking and snippets.

Visibility here is the SQL form of `domain.access.can_view`; the tests keep both in
step. Ranking is `ts_rank` on the item vector, trigram similarity on the title and
the best page hit (`item_pages`); the `simple` configuration is used everywhere, as in
the notebooks. Snippets are made for the page of results only.
"""

import re
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.modules.library.domain.access import REVIEWABLE
from app.modules.library.domain.catalogue_search import (
    ItemFilters,
    ItemSort,
    ItemSource,
    SearchHit,
    Viewer,
)
from app.modules.library.domain.enums import (
    ItemKind,
    ItemLanguage,
    ItemStatus,
    Visibility,
)
from app.modules.library.domain.name_keys import name_key
from app.modules.library.domain.search_query import ParsedQuery, spellings
from app.modules.library.infrastructure.orm import CollectionItem as CollectionRow
from app.modules.library.infrastructure.orm import ExternalDetails as ExternalRow
from app.modules.library.infrastructure.orm import Item as ItemRow
from app.modules.library.infrastructure.orm import ItemPage as PageRow
from app.modules.library.infrastructure.orm import ItemSubject as SubjectRow
from app.modules.library.infrastructure.orm import ItemTag as TagLinkRow
from app.modules.library.infrastructure.orm import ItemTopic as TopicRow
from app.modules.library.infrastructure.orm import MaterialDetails as MaterialRow
from app.modules.library.infrastructure.orm import ShelfEntry as ShelfRow
from app.modules.library.infrastructure.orm import Tag as TagRow
from app.shared.text import search_normalize

from sqlalchemy import (
    ColumnElement,
    Select,
    SmallInteger,
    and_,
    any_,
    case,
    distinct,
    exists,
    false,
    func,
    literal,
    or_,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession

CONFIG = "simple"
HIT_START = "⟦"
HIT_STOP = "⟧"
HEADLINE_OPTIONS = (
    f"StartSel={HIT_START}, StopSel={HIT_STOP}, MaxWords=26, MinWords=12, "
    "MaxFragments=1, ShortWord=2"
)
UZBEK_LANGUAGES = (ItemLanguage.UZ_LATN.value, ItemLanguage.UZ_CYRL.value)
_SPACES = re.compile(r"\s+")

# - - - Who sees what - - -


def _gone_external() -> ColumnElement[bool]:
    return exists(
        select(1).where(
            ExternalRow.item_id == ItemRow.id, ExternalRow.gone_at.is_not(None)
        )
    )


def listed_clause(viewer: Viewer) -> ColumnElement[bool]:
    """Published, not hidden, and open to this kind of audience."""
    clauses: list[ColumnElement[bool]] = [
        ItemRow.status == ItemStatus.PUBLISHED.value,
        ItemRow.visibility != Visibility.HIDDEN.value,
    ]
    if not viewer.signed_in:
        clauses.append(ItemRow.visibility == Visibility.PUBLIC.value)
        clauses.append(_anonymous_external(viewer))
    return and_(*clauses)


def _anonymous_external(viewer: Viewer) -> ColumnElement[bool]:
    if not viewer.anonymous_cards:
        return ItemRow.kind != ItemKind.EXTERNAL.value
    return or_(ItemRow.kind != ItemKind.EXTERNAL.value, ~_gone_external())


def visible_clause(viewer: Viewer) -> ColumnElement[bool]:
    """Items `can_view` lets this viewer see: own, reviewable for staff, or listed."""
    options: list[ColumnElement[bool]] = [listed_clause(viewer)]
    if viewer.user_id is not None:
        options.append(ItemRow.owner_id == viewer.user_id)
    if viewer.staff:
        options.append(ItemRow.status.in_([s.value for s in REVIEWABLE]))
    return or_(*options)


# - - - Filters - - -


def _language_clause(language: str) -> ColumnElement[bool]:
    if language == "uz":
        return ItemRow.language.in_(UZBEK_LANGUAGES)
    return ItemRow.language == language


def _shelf_clause(filters: ItemFilters, viewer: Viewer) -> ColumnElement[bool]:
    if viewer.user_id is None:
        return false()
    conditions = [ShelfRow.item_id == ItemRow.id, ShelfRow.user_id == viewer.user_id]
    if filters.shelf not in (None, "any"):
        conditions.append(ShelfRow.state == str(filters.shelf))
    return exists(select(1).where(*conditions))


def _year_clause(year: int) -> ColumnElement[bool]:
    return or_(
        literal(year, SmallInteger) == any_(ItemRow.years_of_study),
        func.cardinality(ItemRow.years_of_study) == 0,
    )


def filter_clauses(filters: ItemFilters, viewer: Viewer) -> list[ColumnElement[bool]]:
    """The `WHERE` parts of the filters the caller set."""
    clauses: list[ColumnElement[bool]] = []
    if filters.source is not ItemSource.ALL:
        clauses.append(ItemRow.kind == filters.source.value)
    if filters.type is not None:
        clauses.append(ItemRow.type == filters.type.value)
    if filters.language:
        clauses.append(_language_clause(filters.language))
    if filters.has_text is not None:
        clauses.append(ItemRow.has_text == filters.has_text)
    if filters.year_of_study is not None:
        clauses.append(_year_clause(filters.year_of_study))
    if filters.shelf is not None:
        clauses.append(_shelf_clause(filters, viewer))
    return [*clauses, *_link_clauses(filters)]


def _link_clauses(filters: ItemFilters) -> list[ColumnElement[bool]]:
    clauses: list[ColumnElement[bool]] = []
    if filters.subject_id is not None:
        wanted = filters.subject_ids or (filters.subject_id,)
        clauses.append(
            exists(
                select(1).where(
                    SubjectRow.item_id == ItemRow.id,
                    SubjectRow.subject_id.in_(wanted),
                )
            )
        )
    if filters.topic_id is not None:
        clauses.append(
            exists(
                select(1).where(
                    TopicRow.item_id == ItemRow.id,
                    TopicRow.topic_id == filters.topic_id,
                )
            )
        )
    if filters.tag:
        key = name_key(filters.tag)
        clauses.append(
            exists(
                select(1)
                .select_from(TagLinkRow)
                .join(TagRow, TagRow.id == TagLinkRow.tag_id)
                .where(TagLinkRow.item_id == ItemRow.id, TagRow.name_key == key)
            )
        )
    if filters.collection_id is not None:
        clauses.append(
            exists(
                select(1).where(
                    CollectionRow.item_id == ItemRow.id,
                    CollectionRow.collection_id == filters.collection_id,
                )
            )
        )
    if filters.uploader_role is not None:
        clauses.append(
            exists(
                select(1).where(
                    MaterialRow.item_id == ItemRow.id,
                    MaterialRow.uploader_role == filters.uploader_role.value,
                )
            )
        )
    return clauses


# - - - Ranking - - -

# `ColumnElement[Any]`: ORDER BY terms mix numbers, strings, UUIDs and dates.


def _tsquery(query: ParsedQuery) -> ColumnElement[str]:
    return func.to_tsquery(CONFIG, query.match)


def _page_match(query: ParsedQuery) -> ColumnElement[bool]:
    return exists(
        select(1).where(
            PageRow.item_id == ItemRow.id,
            PageRow.search_vector.op("@@")(_tsquery(query)),
        )
    )


def _best_page_rank(query: ParsedQuery) -> ColumnElement[float]:
    tsq = _tsquery(query)
    return (
        select(func.max(func.ts_rank(PageRow.search_vector, tsq)))
        .where(PageRow.item_id == ItemRow.id, PageRow.search_vector.op("@@")(tsq))
        .scalar_subquery()
    )


def _relevance(query: ParsedQuery) -> ColumnElement[float]:
    tsq = _tsquery(query)
    return (
        2.0 * func.ts_rank(ItemRow.search_vector, tsq)
        + func.similarity(ItemRow.title, query.raw)
        + 0.5 * func.coalesce(_best_page_rank(query), 0.0)
    )


def _query_clause(query: ParsedQuery) -> ColumnElement[bool]:
    return or_(
        ItemRow.search_vector.op("@@")(_tsquery(query)),
        ItemRow.title.op("%")(query.raw),
        _page_match(query),
    )


def _newest() -> ColumnElement[Any]:
    return func.coalesce(ItemRow.published_at, ItemRow.created_at)


def _preferred_first(viewer: Viewer) -> list[ColumnElement[Any]]:
    if not viewer.preferred_subject_ids:
        return []
    mine = exists(
        select(1).where(
            SubjectRow.item_id == ItemRow.id,
            SubjectRow.subject_id.in_(viewer.preferred_subject_ids),
        )
    )
    return [case((mine, 0), else_=1)]


def _order(filters: ItemFilters, viewer: Viewer) -> list[ColumnElement[Any]]:
    sort = filters.sort
    if sort is ItemSort.TITLE:
        return [func.lower(ItemRow.title), ItemRow.id.asc()]
    if sort is ItemSort.AUTHOR:
        return [
            func.lower(ItemRow.author_label),
            func.lower(ItemRow.title),
            ItemRow.id.asc(),
        ]
    if sort is ItemSort.NEWEST:
        return [_newest().desc(), ItemRow.id.desc()]
    if filters.query is not None:
        return [_relevance(filters.query).desc(), _newest().desc(), ItemRow.id.asc()]
    return [*_preferred_first(viewer), _newest().desc(), ItemRow.id.desc()]


def search_statement(
    filters: ItemFilters, viewer: Viewer, *, limit: int, offset: int
) -> Select[tuple[UUID]]:
    """The `SELECT id` of a search page."""
    stmt = select(ItemRow.id).where(
        visible_clause(viewer), *filter_clauses(filters, viewer)
    )
    if filters.query is not None:
        stmt = stmt.where(_query_clause(filters.query))
    return stmt.order_by(*_order(filters, viewer)).limit(limit).offset(offset)


# - - - Snippets - - -


def _clean_snippet(headline: str) -> str:
    return _SPACES.sub(
        " ", headline.replace(HIT_START, "").replace(HIT_STOP, "")
    ).strip()


def pick_snippet(original: str, normalised: str) -> str:
    """The headline of the original text if it matched, else of the Latin form."""
    chosen = original if HIT_START in original else normalised
    return _clean_snippet(chosen)


async def page_hits(
    session: AsyncSession, query: ParsedQuery, item_ids: Sequence[UUID]
) -> dict[UUID, SearchHit]:
    """For each item with a matching page: its best page and a snippet of it."""
    if not item_ids:
        return {}
    tsq = _tsquery(query)
    best = (
        select(PageRow.item_id, PageRow.page, PageRow.text, PageRow.text_norm)
        .where(PageRow.item_id.in_(set(item_ids)), PageRow.search_vector.op("@@")(tsq))
        .distinct(PageRow.item_id)
        .order_by(
            PageRow.item_id,
            func.ts_rank(PageRow.search_vector, tsq).desc(),
            PageRow.page,
        )
        .subquery()
    )
    stmt = select(
        best.c.item_id,
        best.c.page,
        func.ts_headline(CONFIG, best.c.text, tsq, HEADLINE_OPTIONS),
        func.ts_headline(CONFIG, best.c.text_norm, tsq, HEADLINE_OPTIONS),
    )
    rows = await session.execute(stmt)
    return {
        item_id: SearchHit(item_id, pick_snippet(original, normalised), page)
        for item_id, page, original, normalised in rows.all()
    }


# - - - Counts and lists - - -


def subject_counts_statement(viewer: Viewer) -> Select[tuple[UUID, int]]:
    """Listed items per subject."""
    return (
        select(SubjectRow.subject_id, func.count(distinct(SubjectRow.item_id)))
        .join(ItemRow, ItemRow.id == SubjectRow.item_id)
        .where(listed_clause(viewer))
        .group_by(SubjectRow.subject_id)
    )


def books_statement(
    *, query: str | None, status: ItemStatus | None, limit: int, offset: int
) -> Select[tuple[UUID]]:
    """The librarian's table of books in any status."""
    stmt = select(ItemRow.id).where(ItemRow.kind == ItemKind.BOOK.value)
    if status is not None:
        stmt = stmt.where(ItemRow.status == status.value)
    if query:
        stmt = stmt.where(
            or_(
                ItemRow.title.icontains(query, autoescape=True),
                ItemRow.author_label.icontains(query, autoescape=True),
                *(
                    ItemRow.search_text.icontains(spelling, autoescape=True)
                    for spelling in spellings(search_normalize(query, "uz"), limit=64)
                ),
            )
        )
    return (
        stmt.order_by(ItemRow.updated_at.desc(), ItemRow.id).limit(limit).offset(offset)
    )
