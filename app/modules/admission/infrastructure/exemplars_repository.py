"""SQL repository of the exemplar essay library."""

from typing import Any
from uuid import UUID

from app.modules.admission.domain.exemplars import Exemplar
from app.modules.admission.infrastructure.orm.catalog import InstitutionRow
from app.modules.admission.infrastructure.orm.exemplars import ExemplarRow

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession


def _like(value: str) -> str:
    """A LIKE pattern matching the text anywhere, with wildcards escaped."""
    esc = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{esc}%"


def _domain(r: ExemplarRow) -> Exemplar:
    """The domain value of a row."""
    return Exemplar(
        id=r.id,
        institution_id=r.institution_id,
        school_name=r.school_name,
        year=r.year,
        kind=r.kind,  # type: ignore[arg-type]
        prompt=r.prompt,
        title=r.title,
        body=r.body,
        word_count=r.word_count,
        source_url=r.source_url,
        source_name=r.source_name,
        tags=tuple(r.tags),
        notes=r.notes,
        status=r.status,  # type: ignore[arg-type]
        language=r.language,
        created_by=r.created_by,
        updated_by=r.updated_by,
        created_at=r.created_at,
        updated_at=r.updated_at,
        lock_version=r.lock_version,
    )


def _values(item: Exemplar) -> dict[str, Any]:
    """Writable columns of the exemplar."""
    return {
        "institution_id": item.institution_id,
        "school_name": item.school_name,
        "year": item.year,
        "kind": item.kind,
        "prompt": item.prompt,
        "title": item.title,
        "body": item.body,
        "word_count": item.word_count,
        "source_url": item.source_url,
        "source_name": item.source_name,
        "tags": list(item.tags),
        "notes": item.notes,
        "status": item.status,
        "language": item.language,
        "updated_by": item.updated_by,
    }


class SqlExemplarRepository:
    """Exemplar essays on PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        """Keep the session."""
        self._s = session

    async def add(self, item: Exemplar) -> None:
        """Store a new exemplar."""
        self._s.add(
            ExemplarRow(
                id=item.id,
                created_by=item.created_by,
                created_at=item.created_at,
                updated_at=item.updated_at,
                lock_version=0,
                **_values(item),
            )
        )
        await self._s.flush()

    async def institution_exists(self, institution_id: UUID) -> bool:
        """Whether the catalog has the institution."""
        found = await self._s.scalar(
            select(InstitutionRow.id).where(InstitutionRow.id == institution_id)
        )
        return found is not None

    async def get(self, exemplar_id: UUID) -> Exemplar | None:
        """One exemplar of any status, or None."""
        row = await self._s.get(ExemplarRow, exemplar_id)
        return _domain(row) if row else None

    async def search(
        self,
        *,
        status: str | None,
        kind: str | None,
        institution_id: UUID | None,
        query: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Exemplar], int]:
        """A page, newest first, and the total of the filter."""
        cond = []
        if status:
            cond.append(ExemplarRow.status == status)
        if kind:
            cond.append(ExemplarRow.kind == kind)
        if institution_id:
            cond.append(ExemplarRow.institution_id == institution_id)
        if query:
            pat = _like(query)
            cond.append(
                or_(
                    ExemplarRow.title.ilike(pat, escape="\\"),
                    ExemplarRow.school_name.ilike(pat, escape="\\"),
                    ExemplarRow.prompt.ilike(pat, escape="\\"),
                )
            )
        total = await self._s.scalar(
            select(func.count()).select_from(ExemplarRow).where(*cond)
        )
        rows = await self._s.scalars(
            select(ExemplarRow)
            .where(*cond)
            .order_by(ExemplarRow.created_at.desc(), ExemplarRow.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return [_domain(r) for r in rows], total or 0

    async def published(self) -> list[Exemplar]:
        """Every published exemplar."""
        rows = await self._s.scalars(
            select(ExemplarRow).where(ExemplarRow.status == "published")
        )
        return [_domain(r) for r in rows]

    async def find_by_source(self, source_url: str, title: str) -> UUID | None:
        """The id of the exemplar with this link and title, if any."""
        found: UUID | None = await self._s.scalar(
            select(ExemplarRow.id)
            .where(ExemplarRow.source_url == source_url, ExemplarRow.title == title)
            .limit(1)
        )
        return found

    async def update(self, item: Exemplar, *, expected_lock: int) -> bool:
        """Write the exemplar and bump its lock; False when the lock is stale."""
        res = await self._s.execute(
            update(ExemplarRow)
            .where(ExemplarRow.id == item.id, ExemplarRow.lock_version == expected_lock)
            .values(**_values(item), lock_version=expected_lock + 1)
            .returning(ExemplarRow.id)
        )
        return res.first() is not None

    async def delete(self, exemplar_id: UUID) -> bool:
        """Remove the exemplar; False when it does not exist."""
        res = await self._s.execute(
            delete(ExemplarRow)
            .where(ExemplarRow.id == exemplar_id)
            .returning(ExemplarRow.id)
        )
        return res.first() is not None
