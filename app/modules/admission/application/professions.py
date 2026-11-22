"""The professions catalogue, the student's ranked picks and ikigai chips."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.domain.errors import AdmissionForbiddenError
from app.modules.admission.domain.professions import (
    ChosenProfession,
    Ikigai,
    Profession,
    clean_chips,
    clean_choice,
    clean_title,
)
from app.modules.admission.ports.fit import ProfessionCatalog
from app.modules.admission.ports.unit_of_work import UowFactory

SEARCH_MAX = 100

Filler = Callable[[AdmissionContext, str, str], Awaitable[Profession]]
"""Drafts the card of a typed-in title: context, title, locale."""


@dataclass(frozen=True, slots=True)
class MyProfession:
    """A picked profession with its rank."""

    profession: Profession
    rank: int


class ProfessionService:
    """Search the catalogue; read and write the caller's picks and ikigai."""

    def __init__(
        self,
        uow_factory: UowFactory,
        catalog: ProfessionCatalog,
        filler: Filler | None = None,
    ) -> None:
        """Keep the unit of work factory, the catalogue and the card drafter."""
        self._uow = uow_factory
        self._catalog = catalog
        self._filler = filler

    def search(self, query: str, limit: int) -> list[Profession]:
        """Professions matching the query, best match first.

        Order: names, then group, fields and tags, then description; the
        catalogue order breaks ties.
        """
        ranked = [
            (r, p) for p in self._catalog.all() if (r := p.rank(query)) is not None
        ]
        ranked.sort(key=lambda x: x[0])
        return [p for _, p in ranked[: min(limit, SEARCH_MAX)]]

    async def mine(self, ctx: AdmissionContext) -> list[MyProfession]:
        """The caller's picks, first choice first."""
        async with self._uow() as uow:
            plan = await uow.profession_plans.get(ctx.user_id)
        custom = {p.id: p for p in plan.custom}
        out: list[MyProfession] = []
        for c in plan.chosen:
            p = self._catalog.get(c.profession_id) or custom.get(c.profession_id)
            if p is not None:
                out.append(MyProfession(p, c.rank))
        return out

    async def choose(
        self, ctx: AdmissionContext, items: list[tuple[str, int]]
    ) -> list[MyProfession]:
        """Replace the picks (at most five in all, known, once each).

        Typed-in professions that are not picked any more are dropped.
        """
        async with self._uow() as uow:
            plan = await uow.profession_plans.get(ctx.user_id)
            known = {p.id for p in self._catalog.all()} | {p.id for p in plan.custom}
            chosen: tuple[ChosenProfession, ...] = clean_choice(items, known)
            picked = {c.profession_id for c in chosen}
            kept = tuple(p for p in plan.custom if p.id in picked)
            await uow.profession_plans.save_chosen(ctx.user_id, chosen)
            if kept != plan.custom:
                await uow.profession_plans.save_custom(ctx.user_id, kept)
            await uow.commit()
        return await self.mine(ctx)

    async def fill(self, ctx: AdmissionContext, title: str, locale: str) -> Profession:
        """Draft the card of a typed-in title and keep it for the caller.

        The same title again returns the stored card.
        """
        title = clean_title(title)
        if self._filler is None:
            raise AdmissionForbiddenError(params={"permission": "professions:fill"})
        async with self._uow() as uow:
            plan = await uow.profession_plans.get(ctx.user_id)
        picked = {c.profession_id for c in plan.chosen}
        mine = tuple(p for p in plan.custom if p.id in picked)
        folded = title.casefold()
        for p in plan.custom:
            if any(n.casefold() == folded for n in p.names.values()):
                return p
        card = await self._filler(ctx, title, locale)
        names = {k: v for k, v in card.names.items() if v}
        card = replace(card, names=names or {locale: title})
        async with self._uow() as uow:
            await uow.profession_plans.save_custom(ctx.user_id, (*mine, card))
            await uow.commit()
        return card

    async def ikigai(self, ctx: AdmissionContext) -> Ikigai:
        """The caller's ikigai chips."""
        async with self._uow() as uow:
            return (await uow.profession_plans.get(ctx.user_id)).ikigai

    async def set_ikigai(
        self, ctx: AdmissionContext, answers: dict[str, list[str]]
    ) -> Ikigai:
        """Replace the ikigai chips (each list ≤ 8 items, ≤ 60 chars)."""
        clean = Ikigai(**{k: clean_chips(k, v) for k, v in answers.items()})
        async with self._uow() as uow:
            await uow.profession_plans.save_ikigai(ctx.user_id, clean)
            await uow.commit()
        return clean
