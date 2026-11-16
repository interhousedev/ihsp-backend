"""Preferences, matches and swipe decisions of the "discover" feature."""

import dataclasses
import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Final
from uuid import UUID

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.chooser import ListService
from app.modules.admission.domain.admit_rate import admission_rate
from app.modules.admission.domain.chooser import CatalogInstitution
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
)
from app.modules.admission.domain.matching import (
    Overlap,
    PreferenceAnswers,
    Status,
    cost_usd,
    match,
    preference_tags,
    status_of,
    university_tags,
)
from app.modules.admission.ports.matching import MatchUnitOfWork
from app.shared.clock import Clock

MatchUowFactory = Callable[[], MatchUnitOfWork]
DEFAULT_LIMIT: Final = 20
MAX_LIMIT: Final = 50


@dataclass(frozen=True, slots=True)
class PreferenceView:
    """Stored answers with their tags."""

    answers: PreferenceAnswers
    tags: list[str]
    completed: bool
    updated_at: dt.datetime | None


@dataclass(frozen=True, slots=True)
class MatchItem:
    """A university with its score for one student."""

    institution: CatalogInstitution
    match_pct: int
    overlap: Overlap
    admission_rate: float | None
    cost_after_aid_usd: Decimal | None
    status: Status | None


def _applicant(ctx: AdmissionContext) -> None:
    if not ctx.admission.is_applicant:
        raise AdmissionForbiddenError(params={"permission": "matching:write"})


async def _drop_untouched(uow: MatchUnitOfWork, student_id: UUID, iid: UUID) -> None:
    """Remove the list entry a swipe created, unless the student edited it."""
    entry = await uow.shortlist.find(student_id, iid)
    if (
        entry is not None
        and entry.status == "considering"
        and entry.notes is None
        and entry.bucket is None
    ):
        await uow.shortlist.delete(entry.id)


def _view(a: PreferenceAnswers, at: dt.datetime | None) -> PreferenceView:
    return PreferenceView(a, preference_tags(a), a.completed, at)


class MatchService:
    """Student-scoped: answers, ranked undecided universities, decisions."""

    def __init__(
        self, uow_factory: MatchUowFactory, chooser: ListService, clock: Clock
    ) -> None:
        """Keep the collaborators."""
        self._uow = uow_factory
        self._list = chooser
        self._clock = clock

    async def preferences(self, ctx: AdmissionContext) -> PreferenceView:
        """The caller's answers (empty before the first save)."""
        async with self._uow() as uow:
            row = await uow.preferences.get(ctx.user_id)
        return _view(*row) if row else _view(PreferenceAnswers(), None)

    async def save_preferences(
        self, ctx: AdmissionContext, patch: dict[str, object]
    ) -> PreferenceView:
        """Merge the sent answers into the stored ones (partial update)."""
        _applicant(ctx)
        now = self._clock.now()
        async with self._uow() as uow:
            row = await uow.preferences.get(ctx.user_id)
            current = row[0] if row else PreferenceAnswers()
            merged = dataclasses.replace(current, **patch)  # type: ignore[arg-type]
            await uow.preferences.save(ctx.user_id, merged, now)
            await uow.commit()
        return _view(merged, now)

    async def matches(self, ctx: AdmissionContext, limit: int) -> list[MatchItem]:
        """Undecided, unlisted universities, best match first."""
        limit = max(1, min(limit, MAX_LIMIT))
        async with self._uow() as uow:
            row = await uow.preferences.get(ctx.user_id)
            decided = await uow.decisions.decided(ctx.user_id)
            listed = {
                e.institution_id for e in await uow.shortlist.entries(ctx.user_id)
            }
            insts = await uow.catalog.institutions()
        wanted = preference_tags(row[0]) if row else []
        items: list[MatchItem] = []
        for inst in insts:
            if inst.id in decided or inst.id in listed:
                continue
            pct, overlap = match(wanted, university_tags(inst))
            rate = admission_rate(inst)
            items.append(
                MatchItem(inst, pct, overlap, rate, cost_usd(inst), status_of(rate))
            )
        items.sort(key=lambda m: (-m.match_pct, m.institution.name.casefold()))
        return items[:limit]

    async def decide(
        self, ctx: AdmissionContext, institution_id: UUID, decision: str
    ) -> None:
        """Record a swipe; `interested` puts the university on the list if absent."""
        _applicant(ctx)
        async with self._uow() as uow:
            if await uow.catalog.institution(institution_id) is None:
                raise AdmissionNotFoundError()
            was = await uow.decisions.get(ctx.user_id, institution_id)
            created = was == "interested" and await uow.decisions.created_entry(
                ctx.user_id, institution_id
            )
            existing = await uow.shortlist.find(ctx.user_id, institution_id)
        if decision == "interested":
            if existing is None:
                await self._list.add(ctx, institution_id)
                created = True
        elif created:
            async with self._uow() as uow:
                await _drop_untouched(uow, ctx.user_id, institution_id)
                await uow.commit()
            created = False
        async with self._uow() as uow:
            await uow.decisions.set(
                ctx.user_id,
                institution_id,
                decision,
                self._clock.now(),
                created_list_entry=created and decision == "interested",
            )
            await uow.commit()

    async def undo(self, ctx: AdmissionContext, institution_id: UUID) -> None:
        """Forget the swipe; a list entry it created and nobody touched goes too."""
        _applicant(ctx)
        async with self._uow() as uow:
            if await uow.catalog.institution(institution_id) is None:
                raise AdmissionNotFoundError()
            was = await uow.decisions.get(ctx.user_id, institution_id)
            created = was == "interested" and await uow.decisions.created_entry(
                ctx.user_id, institution_id
            )
            await uow.decisions.delete(ctx.user_id, institution_id)
            if created:
                await _drop_untouched(uow, ctx.user_id, institution_id)
            await uow.commit()
