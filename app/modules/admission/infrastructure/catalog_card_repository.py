"""SQL repository of the curator's institution card."""

import datetime as dt
from typing import Any
from uuid import UUID

from app.modules.admission.domain.catalog_card import CardFact, fact_input
from app.modules.admission.domain.chooser import CatalogScholarship
from app.modules.admission.infrastructure.chooser_repositories import _scholarship
from app.modules.admission.infrastructure.orm.catalog import (
    FactRow,
    InstitutionRow,
    ScholarshipRow,
    SourceRow,
)
from app.shared.ids import new_id

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession


class SqlCatalogCardRepository:
    """Facts, scholarships and description of one institution."""

    def __init__(self, session: AsyncSession) -> None:
        """Keep the open session."""
        self._s = session

    async def facts(self, institution_id: UUID) -> list[CardFact]:
        """Published facts with their source."""
        q = (
            select(FactRow, SourceRow.url)
            .join(SourceRow, SourceRow.id == FactRow.source_id, isouter=True)
            .where(
                FactRow.entity_kind == "institution",
                FactRow.entity_id == institution_id,
                FactRow.status == "published",
            )
            .order_by(FactRow.key, FactRow.cycle.nulls_first())
        )
        out: dict[str, CardFact] = {}
        for f, url in (await self._s.execute(q)).tuples():
            out[f.key] = CardFact(
                key=f.key,
                value=fact_input(f.key, f.value, f.unit),
                source_url=url,
                year=f.cycle,
                note=f.excerpt,
                verified=f.reviewer_id is not None
                or f.confidence in ("official", "structured_api"),
                updated_at=f.updated_at,
            )
        return list(out.values())

    async def set_verified(
        self, institution_id: UUID, key: str, reviewer_id: UUID | None
    ) -> None:
        """Set or clear the reviewer of the published rows of a key."""
        await self._s.execute(
            update(FactRow)
            .where(
                FactRow.entity_kind == "institution",
                FactRow.entity_id == institution_id,
                FactRow.key == key,
                FactRow.status == "published",
            )
            .values(reviewer_id=reviewer_id, confidence="manual")
        )

    async def delete_fact(self, institution_id: UUID, key: str) -> bool:
        """Delete the rows of a key."""
        result = await self._s.execute(
            delete(FactRow).where(
                FactRow.entity_kind == "institution",
                FactRow.entity_id == institution_id,
                FactRow.key == key,
            )
        )
        return bool(result.rowcount)  # type: ignore[attr-defined]

    async def description(self, institution_id: UUID) -> dict[str, str] | None:
        """The stored description."""
        row = await self._s.get(InstitutionRow, institution_id)
        return None if row is None else row.description

    async def set_description(
        self, institution_id: UUID, value: dict[str, str] | None, now: dt.datetime
    ) -> None:
        """Replace the description."""
        await self._s.execute(
            update(InstitutionRow)
            .where(InstitutionRow.id == institution_id)
            .values(description=value)
        )

    async def scholarships(self, institution_id: UUID) -> list[CatalogScholarship]:
        """Scholarships of the institution."""
        rows = await self._s.scalars(
            select(ScholarshipRow)
            .where(ScholarshipRow.institution_id == institution_id)
            .order_by(ScholarshipRow.name)
        )
        return [_scholarship(r) for r in rows]

    async def create_scholarship(
        self, institution_id: UUID, values: dict[str, Any]
    ) -> UUID:
        """Insert a published scholarship."""
        row = ScholarshipRow(
            id=new_id(), institution_id=institution_id, status="published", **values
        )
        self._s.add(row)
        await self._s.flush()
        return row.id

    async def update_scholarship(
        self, institution_id: UUID, scholarship_id: UUID, values: dict[str, Any]
    ) -> bool:
        """Overwrite columns of one scholarship."""
        row = await self._s.get(ScholarshipRow, scholarship_id)
        if row is None or row.institution_id != institution_id:
            return False
        for key, value in values.items():
            setattr(row, key, value)
        await self._s.flush()
        return True

    async def delete_scholarship(
        self, institution_id: UUID, scholarship_id: UUID
    ) -> bool:
        """Delete one scholarship."""
        row = await self._s.get(ScholarshipRow, scholarship_id)
        if row is None or row.institution_id != institution_id:
            return False
        await self._s.delete(row)
        await self._s.flush()
        return True
