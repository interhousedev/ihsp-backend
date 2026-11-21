"""SQLAlchemy repositories of fit preferences and the professions plan."""

import datetime as dt
from uuid import UUID

from app.modules.admission.domain.professions import (
    ChosenProfession,
    Ikigai,
    ProfessionPlan,
)
from app.modules.admission.infrastructure.orm.fit import (
    FitPreferencesRow,
    ProfessionPlanRow,
)

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

_IKIGAI = ("love", "good_at", "needs", "paid")


class SqlFitPreferenceRepository:
    """Ratings, one row per student."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the session."""
        self._s = session

    async def get(self, student_id: UUID) -> tuple[dict[str, int], dt.datetime] | None:
        """Saved ratings and when they were saved, or None when never saved."""
        row = await self._s.get(FitPreferencesRow, student_id)
        return None if row is None else (dict(row.ratings), row.updated_at)

    async def save(self, student_id: UUID, ratings: dict[str, int]) -> dt.datetime:
        """Replace the ratings; returns the save time."""
        stmt = insert(FitPreferencesRow).values(student_id=student_id, ratings=ratings)
        res = await self._s.execute(
            stmt.on_conflict_do_update(
                index_elements=["student_id"],
                set_={"ratings": ratings, "updated_at": func.now()},
            ).returning(FitPreferencesRow.updated_at)
        )
        return res.scalar_one()


class SqlProfessionPlanRepository:
    """Chosen professions and ikigai chips, one row per student."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the session."""
        self._s = session

    async def get(self, student_id: UUID) -> ProfessionPlan:
        """The plan; empty when nothing was saved."""
        row = await self._s.get(ProfessionPlanRow, student_id)
        if row is None:
            return ProfessionPlan(student_id)
        chosen = sorted(
            (ChosenProfession(c["profession_id"], c["rank"]) for c in row.chosen),
            key=lambda c: c.rank,
        )
        ik = row.ikigai
        return ProfessionPlan(
            student_id,
            tuple(chosen),
            Ikigai(**{k: tuple(ik.get(k, ())) for k in _IKIGAI}),
        )

    async def save_chosen(
        self, student_id: UUID, chosen: tuple[ChosenProfession, ...]
    ) -> None:
        """Replace the ranked professions."""
        value = [{"profession_id": c.profession_id, "rank": c.rank} for c in chosen]
        await self._upsert(student_id, {"chosen": value})

    async def save_ikigai(self, student_id: UUID, ikigai: Ikigai) -> None:
        """Replace the ikigai chips."""
        await self._upsert(
            student_id, {"ikigai": {k: list(getattr(ikigai, k)) for k in _IKIGAI}}
        )

    async def _upsert(self, student_id: UUID, values: dict[str, object]) -> None:
        stmt = insert(ProfessionPlanRow).values(student_id=student_id, **values)
        await self._s.execute(
            stmt.on_conflict_do_update(
                index_elements=["student_id"],
                set_={**values, "updated_at": func.now()},
            )
        )
