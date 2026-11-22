"""SQL storage of country facts; each call opens and commits its own session."""

from typing import Any
from uuid import UUID

from app.modules.admission.domain.country_facts import CountryFacts
from app.modules.admission.infrastructure.orm.country_facts import CountryFactsRow

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _facts(row: CountryFactsRow) -> CountryFacts:
    return CountryFacts(
        country=row.country,
        as_of=row.as_of,
        facts=dict(row.facts or {}),
        status="verified" if row.status == "verified" else "draft",
        verified_by=row.verified_by,
        updated_at=row.updated_at,
        seeded=row.verified_by is None,
    )


class SqlCountryFactsRepository:
    """Country facts on the shared sessionmaker."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Keep the sessionmaker."""
        self._sm = sessionmaker

    async def get_many(self, codes: list[str]) -> list[CountryFacts]:
        """The stored rows of the codes, in code order."""
        if not codes:
            return []
        async with self._sm() as session:
            rows = (
                await session.scalars(
                    select(CountryFactsRow).where(CountryFactsRow.country.in_(codes))
                )
            ).all()
        by_code = {r.country: _facts(r) for r in rows}
        return [by_code[c] for c in codes if c in by_code]

    async def list_all(self) -> list[CountryFacts]:
        """Every stored row, by country code."""
        async with self._sm() as session:
            rows = await session.scalars(
                select(CountryFactsRow).order_by(CountryFactsRow.country)
            )
            return [_facts(r) for r in rows]

    async def save(
        self,
        country: str,
        *,
        as_of: str,
        facts: dict[str, dict[str, Any]],
        editor: UUID,
        verified: bool,
    ) -> CountryFacts:
        """Create or replace the row as a staff edit."""
        status = "verified" if verified else "draft"
        async with self._sm.begin() as session:
            row = await session.get(CountryFactsRow, country)
            if row is None:
                row = CountryFactsRow(country=country)
                session.add(row)
            row.as_of = as_of
            row.facts = facts
            row.status = status
            row.verified_by = editor
            await session.flush()
            await session.refresh(row)
            return _facts(row)

    async def set_verified(self, country: str, editor: UUID) -> CountryFacts | None:
        """Mark the row verified; None without a row."""
        async with self._sm.begin() as session:
            row = await session.get(CountryFactsRow, country)
            if row is None:
                return None
            row.status = "verified"
            row.verified_by = editor
            await session.flush()
            await session.refresh(row)
            return _facts(row)
