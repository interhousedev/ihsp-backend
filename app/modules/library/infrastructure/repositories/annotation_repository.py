"""SQL repository of annotations. Every query is scoped to one user."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.library.domain.enums import AnnotationColor, AnnotationKind
from app.modules.library.domain.reader_annotation import Annotation
from app.modules.library.infrastructure.orm import Annotation as AnnotationRow
from app.modules.library.ports.annotation_repository import (
    AnnotationCursor,
    AnnotationFilter,
)
from app.modules.library.infrastructure.repositories.rowcount import rows_affected

from sqlalchemy import Select, and_, delete, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession


def _annotation_from(row: AnnotationRow) -> Annotation:
    return Annotation(
        id=row.id,
        user_id=row.user_id,
        item_id=row.item_id,
        file_id=row.file_id,
        kind=AnnotationKind(row.kind),
        locator=dict(row.locator),
        quote=row.quote,
        note=row.note,
        color=AnnotationColor(row.color),
        client_id=row.client_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
        deleted_at=row.deleted_at,
    )


def _like_pattern(text: str) -> str:
    """`%text%` with the LIKE wildcards of `text` escaped (escape character `\\`)."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _filtered(
    query: Select[tuple[AnnotationRow]], f: AnnotationFilter
) -> Select[tuple[AnnotationRow]]:
    if f.item_id is not None:
        query = query.where(AnnotationRow.item_id == f.item_id)
    if f.kind is not None:
        query = query.where(AnnotationRow.kind == f.kind.value)
    if f.color is not None:
        query = query.where(AnnotationRow.color == f.color.value)
    if f.query:
        pattern = _like_pattern(f.query)
        query = query.where(
            or_(
                AnnotationRow.quote.ilike(pattern, escape="\\"),
                AnnotationRow.note.ilike(pattern, escape="\\"),
            )
        )
    return query


class SqlAnnotationRepository:
    """Stores annotations in `library.annotations`."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the unit of work's session."""
        self.session = session

    async def add(self, annotation: Annotation) -> bool:
        """Insert a new annotation; False when the user's client id already exists."""
        statement = (
            insert(AnnotationRow)
            .values(
                id=annotation.id,
                user_id=annotation.user_id,
                item_id=annotation.item_id,
                file_id=annotation.file_id,
                kind=annotation.kind.value,
                locator=dict(annotation.locator),
                quote=annotation.quote,
                note=annotation.note,
                color=annotation.color.value,
                client_id=annotation.client_id,
                deleted_at=annotation.deleted_at,
                created_at=annotation.created_at,
                updated_at=annotation.updated_at,
            )
            .on_conflict_do_nothing(
                index_elements=[AnnotationRow.user_id, AnnotationRow.client_id]
            )
        )
        result = await self.session.execute(statement)
        return bool(rows_affected(result))

    async def save(self, annotation: Annotation) -> None:
        """Update note, colour, timestamps and the deletion mark."""
        row = (
            await self.session.execute(
                select(AnnotationRow).where(
                    AnnotationRow.id == annotation.id,
                    AnnotationRow.user_id == annotation.user_id,
                )
            )
        ).scalar_one()
        row.note = annotation.note
        row.color = annotation.color.value
        row.updated_at = annotation.updated_at
        row.deleted_at = annotation.deleted_at
        await self.session.flush()

    async def get(self, user_id: UUID, annotation_id: UUID) -> Annotation | None:
        """The user's live annotation, or None (also for a deleted one)."""
        row = (
            await self.session.execute(
                select(AnnotationRow).where(
                    AnnotationRow.id == annotation_id,
                    AnnotationRow.user_id == user_id,
                    AnnotationRow.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        return _annotation_from(row) if row else None

    async def get_by_client_id(
        self, user_id: UUID, client_id: UUID
    ) -> Annotation | None:
        """The user's annotation created with this client id, deleted ones too."""
        row = (
            await self.session.execute(
                select(AnnotationRow).where(
                    AnnotationRow.user_id == user_id,
                    AnnotationRow.client_id == client_id,
                )
            )
        ).scalar_one_or_none()
        return _annotation_from(row) if row else None

    async def find_any(self, user_id: UUID, ids: Sequence[UUID]) -> list[Annotation]:
        """The user's annotations whose id or client id is in `ids`, deleted too."""
        if not ids:
            return []
        wanted = set(ids)
        rows = await self.session.execute(
            select(AnnotationRow).where(
                AnnotationRow.user_id == user_id,
                or_(AnnotationRow.id.in_(wanted), AnnotationRow.client_id.in_(wanted)),
            )
        )
        return [_annotation_from(row) for row in rows.scalars()]

    async def list_page(
        self,
        user_id: UUID,
        *,
        filters: AnnotationFilter,
        after: AnnotationCursor | None,
        limit: int,
    ) -> list[Annotation]:
        """Live annotations, most recently changed first, continuing after the cursor."""
        query = select(AnnotationRow).where(
            AnnotationRow.user_id == user_id, AnnotationRow.deleted_at.is_(None)
        )
        query = _filtered(query, filters)
        if after is not None:
            query = query.where(
                or_(
                    AnnotationRow.updated_at < after.updated_at,
                    and_(
                        AnnotationRow.updated_at == after.updated_at,
                        AnnotationRow.id < after.id,
                    ),
                )
            )
        query = query.order_by(
            AnnotationRow.updated_at.desc(), AnnotationRow.id.desc()
        ).limit(limit)
        rows = await self.session.execute(query)
        return [_annotation_from(row) for row in rows.scalars()]

    async def list_for_item(self, user_id: UUID, item_id: UUID) -> list[Annotation]:
        """Live annotations of the user on the item, oldest first."""
        return await self.list_for_user(user_id, item_id=item_id)

    async def list_for_user(
        self, user_id: UUID, *, item_id: UUID | None
    ) -> list[Annotation]:
        """All live annotations (of one item when given), oldest first."""
        query = select(AnnotationRow).where(
            AnnotationRow.user_id == user_id, AnnotationRow.deleted_at.is_(None)
        )
        if item_id is not None:
            query = query.where(AnnotationRow.item_id == item_id)
        rows = await self.session.execute(
            query.order_by(AnnotationRow.created_at, AnnotationRow.id)
        )
        return [_annotation_from(row) for row in rows.scalars()]

    async def delete_all(self, user_id: UUID) -> int:
        """Delete every annotation of the user, deleted ones too (account closure)."""
        result = await self.session.execute(
            delete(AnnotationRow).where(AnnotationRow.user_id == user_id)
        )
        return rows_affected(result)
