"""Ports: fit preferences, the professions plan and the professions catalogue."""

import datetime as dt
from typing import Protocol
from uuid import UUID

from app.modules.admission.domain.professions import (
    ChosenProfession,
    Ikigai,
    Profession,
    ProfessionPlan,
)


class FitPreferenceRepository(Protocol):
    """A student's 1..10 ratings of what matters in a university."""

    async def get(self, student_id: UUID) -> tuple[dict[str, int], dt.datetime] | None:
        """Saved ratings and when they were saved, or None when never saved."""
        ...

    async def save(self, student_id: UUID, ratings: dict[str, int]) -> dt.datetime:
        """Replace the ratings; returns the save time."""
        ...


class ProfessionPlanRepository(Protocol):
    """A student's ranked professions and ikigai chips."""

    async def get(self, student_id: UUID) -> ProfessionPlan:
        """The plan; empty when nothing was saved."""
        ...

    async def save_chosen(
        self, student_id: UUID, chosen: tuple[ChosenProfession, ...]
    ) -> None:
        """Replace the ranked professions."""
        ...

    async def save_custom(
        self, student_id: UUID, custom: tuple[Profession, ...]
    ) -> None:
        """Replace the professions the student typed in."""
        ...

    async def save_ikigai(self, student_id: UUID, ikigai: Ikigai) -> None:
        """Replace the ikigai chips."""
        ...


class ProfessionCatalog(Protocol):
    """The committed ISCO-08 snapshot."""

    def all(self) -> tuple[Profession, ...]:
        """Every profession, in id order."""
        ...

    def get(self, profession_id: str) -> Profession | None:
        """One profession by ISCO code."""
        ...
