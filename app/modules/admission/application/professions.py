"""The professions catalogue, the student's ranked picks and ikigai chips."""

from dataclasses import dataclass

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.domain.professions import (
    ChosenProfession,
    Ikigai,
    Profession,
    clean_chips,
    clean_choice,
)
from app.modules.admission.ports.fit import ProfessionCatalog
from app.modules.admission.ports.unit_of_work import UowFactory

SEARCH_MAX = 100


@dataclass(frozen=True, slots=True)
class MyProfession:
    """A picked profession with its rank."""

    profession: Profession
    rank: int


class ProfessionService:
    """Search the catalogue; read and write the caller's picks and ikigai."""

    def __init__(self, uow_factory: UowFactory, catalog: ProfessionCatalog) -> None:
        """Keep the unit of work factory and the catalogue."""
        self._uow = uow_factory
        self._catalog = catalog

    def search(self, query: str, limit: int) -> list[Profession]:
        """Professions whose id or any-language name contains the query."""
        found = (p for p in self._catalog.all() if p.matches(query))
        return [p for _, p in zip(range(min(limit, SEARCH_MAX)), found, strict=False)]

    async def mine(self, ctx: AdmissionContext) -> list[MyProfession]:
        """The caller's picks, first choice first."""
        async with self._uow() as uow:
            plan = await uow.profession_plans.get(ctx.user_id)
        out: list[MyProfession] = []
        for c in plan.chosen:
            p = self._catalog.get(c.profession_id)
            if p is not None:
                out.append(MyProfession(p, c.rank))
        return out

    async def choose(
        self, ctx: AdmissionContext, items: list[tuple[str, int]]
    ) -> list[MyProfession]:
        """Replace the picks (at most five, known, once each)."""
        chosen: tuple[ChosenProfession, ...] = clean_choice(
            items, {p.id for p in self._catalog.all()}
        )
        async with self._uow() as uow:
            await uow.profession_plans.save_chosen(ctx.user_id, chosen)
            await uow.commit()
        return await self.mine(ctx)

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
