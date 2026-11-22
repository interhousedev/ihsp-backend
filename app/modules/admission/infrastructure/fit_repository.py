"""SQLAlchemy repositories of fit preferences and the professions plan."""

import datetime as dt
from typing import Any
from uuid import UUID

from app.modules.admission.domain.professions import (
    ChosenProfession,
    Ikigai,
    Profession,
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


def _custom_dump(p: Profession) -> dict[str, Any]:
    return {
        "id": p.id,
        "group": p.group,
        "names": p.names,
        "descriptions": p.descriptions,
        "ai_exposure": p.ai_exposure,
        "ai_risk": p.ai_risk,
        "horizon": p.horizon,
        "related_fields": list(p.related_fields),
        "salary_band": p.salary_band,
        "isco_id": p.isco_id,
    }


def _custom_of(d: dict[str, Any]) -> Profession:
    return Profession(
        id=d["id"],
        group=d["group"],
        names=d["names"],
        ai_exposure=d["ai_exposure"],
        ai_risk=d["ai_risk"],
        horizon=d["horizon"],
        related_fields=tuple(d["related_fields"]),
        salary_band=d.get("salary_band"),
        descriptions=d.get("descriptions") or {},
        custom=True,
        isco_id=d.get("isco_id"),
    )


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
            tuple(_custom_of(c) for c in row.custom),
        )

    async def save_chosen(
        self, student_id: UUID, chosen: tuple[ChosenProfession, ...]
    ) -> None:
        """Replace the ranked professions."""
        value = [{"profession_id": c.profession_id, "rank": c.rank} for c in chosen]
        await self._upsert(student_id, {"chosen": value})

    async def save_custom(
        self, student_id: UUID, custom: tuple[Profession, ...]
    ) -> None:
        """Replace the professions the student typed in."""
        await self._upsert(student_id, {"custom": [_custom_dump(p) for p in custom]})

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
