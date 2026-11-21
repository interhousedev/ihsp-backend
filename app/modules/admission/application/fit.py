"""Fit of every list entry to the student: affordability, goals, profile, traits."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.chooser import ListService
from app.modules.admission.application.fit_preferences import view_of
from app.modules.admission.application.study_focus import load_study_focus
from app.modules.admission.domain.fit import (
    EntryFit,
    FitResult,
    StudentFit,
    compute_fit,
    default_ratings,
)
from app.modules.admission.domain.professions import Profession
from app.modules.admission.ports.fit import ProfessionCatalog
from app.modules.admission.ports.unit_of_work import UowFactory


@dataclass(frozen=True, slots=True)
class EntryFitView:
    """The fit of one list entry."""

    list_entry_id: UUID
    institution_id: UUID
    fit: FitResult


@dataclass(frozen=True, slots=True)
class ListFit:
    """Axis weights and the fit of each entry, in list order."""

    weights: dict[str, float]
    items: tuple[EntryFitView, ...]


class FitService:
    """Scores the caller's list from saved preferences and plan."""

    def __init__(
        self,
        uow_factory: UowFactory,
        chooser: ListService,
        professions: ProfessionCatalog,
    ) -> None:
        """Keep the collaborators."""
        self._uow = uow_factory
        self._chooser = chooser
        self._professions = professions

    async def _student(self, student_id: UUID) -> tuple[StudentFit, dict[str, float]]:
        async with self._uow() as uow:
            saved = await uow.fit_preferences.get(student_id)
            plan = await uow.profession_plans.get(student_id)
            band = await uow.shortlist.budget_band(student_id)
            if band is None:
                survey = await uow.preferences.get(student_id)
                band = survey[0].budget if survey is not None else None
            focus = await load_study_focus(uow, student_id)
            scores = await uow.test_scores.entries(student_id)
        prefs = (
            view_of(default_ratings(), False, None)
            if saved is None
            else view_of(default_ratings() | saved[0], True, saved[1])
        )
        chosen: list[Profession] = []
        for c in sorted(plan.chosen, key=lambda c: c.rank):
            p = self._professions.get(c.profession_id)
            if p is not None:
                chosen.append(p)
        student = StudentFit(
            prefs.ratings, band, tuple(chosen), focus.field_ids, bool(scores)
        )
        return student, prefs.weights

    async def list_fit(self, ctx: AdmissionContext, locale: str) -> ListFit:
        """Fit of each entry of the caller's own list."""
        items = await self._chooser.view(ctx, ctx.user_id)
        student, weights = await self._student(ctx.user_id)
        out = tuple(
            EntryFitView(
                i.entry.id,
                i.institution.id,
                compute_fit(
                    student,
                    EntryFit(i.institution, i.estimate.label),
                    weights,
                    locale,
                ),
            )
            for i in items
        )
        out = tuple(sorted(out, key=_rank, reverse=True))
        return ListFit(weights, out)


def _rank(v: EntryFitView) -> float:
    """Sort key: the total, discounted when much of it is unknown."""
    if v.fit.total is None:
        return -1.0
    return v.fit.total * (0.5 + 0.5 * v.fit.known_share)
