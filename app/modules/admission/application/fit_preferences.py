"""The student's fit preference ratings (the radar) and the weights they give."""

import datetime as dt
from dataclasses import dataclass

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.domain.fit import (
    DEFAULT_WEIGHTS,
    default_ratings,
    weights_of,
)
from app.modules.admission.domain.fit_ratings import clean_ratings
from app.modules.admission.ports.unit_of_work import UowFactory


@dataclass(frozen=True, slots=True)
class FitPreferences:
    """Ratings, the axis weights derived from them, and the save time."""

    ratings: dict[str, int]
    weights: dict[str, float]
    updated_at: dt.datetime | None


def view_of(
    ratings: dict[str, int], saved: bool, at: dt.datetime | None
) -> FitPreferences:
    """Weights are the research defaults until the student saves ratings."""
    return FitPreferences(
        ratings, weights_of(ratings) if saved else dict(DEFAULT_WEIGHTS), at
    )


class FitPreferenceService:
    """Reads and writes the caller's ratings."""

    def __init__(self, uow_factory: UowFactory) -> None:
        """Keep the unit of work factory."""
        self._uow = uow_factory

    async def get(self, ctx: AdmissionContext) -> FitPreferences:
        """The caller's ratings (defaults when never saved)."""
        async with self._uow() as uow:
            row = await uow.fit_preferences.get(ctx.user_id)
        if row is None:
            return view_of(default_ratings(), False, None)
        return view_of(default_ratings() | row[0], True, row[1])

    async def put(
        self, ctx: AdmissionContext, ratings: dict[str, int]
    ) -> FitPreferences:
        """Replace the caller's ratings."""
        clean = clean_ratings(ratings)
        async with self._uow() as uow:
            at = await uow.fit_preferences.save(ctx.user_id, clean)
            await uow.commit()
        return view_of(clean, True, at)
