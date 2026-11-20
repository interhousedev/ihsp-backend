"""The prompt map and idea fit: which essay can answer which prompts.

Both read the catalog of supplemental prompts and its embeddings. Neither calls a
language model; a missing embedding model only makes the answer "unavailable".
"""

from dataclasses import dataclass, replace
from typing import Final

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.essay_prompts import FlowGate
from app.modules.admission.domain.errors import InvalidAnswerError
from app.modules.admission.domain.essay_flow import (
    PromptMap,
    PromptRef,
    build_map,
    common_app_refs,
    cosine_distance,
    delta_for,
    fit_score,
    prompt_key,
)
from app.modules.admission.domain.essays import IDEA_MAX
from app.modules.admission.ports.consent import AI
from app.modules.admission.ports.essay_flow import PromptVectors
from app.modules.admission.ports.unit_of_work import AdmissionUnitOfWork, UowFactory

FIT_LIMIT: Final = 20
NO_MODEL: Final = "none"


@dataclass(frozen=True, slots=True)
class PromptMapView:
    """The map, whether vectors were available, and the keys the student covered."""

    map: PromptMap
    available: bool
    covered: frozenset[str]


@dataclass(frozen=True, slots=True)
class PromptFit:
    """How well an idea fits one prompt."""

    prompt: PromptRef
    distance: float
    score: int


@dataclass(frozen=True, slots=True)
class IdeaFit:
    """Prompts not yet covered, best fit first; empty when unavailable."""

    available: bool
    model: str
    delta: float
    items: tuple[PromptFit, ...]


class EssayPromptMap:
    """Prompt map of the catalog and idea fit against uncovered prompts."""

    def __init__(
        self, uow_factory: UowFactory, gate: FlowGate, vectors: PromptVectors
    ) -> None:
        """Keep the unit of work factory, the gate and the prompt vectors."""
        self._uow = uow_factory
        self._gate = gate
        self._vectors = vectors

    async def prompt_map(self, ctx: AdmissionContext) -> PromptMapView:
        """Group every prompt (Common App and supplements); mark the listed ones."""
        await self._gate.owner(ctx)
        async with self._uow() as uow:
            refs = [*common_app_refs(), *await uow.prompt_catalog.all()]
            listed = {
                e.institution_id for e in await uow.shortlist.entries(ctx.user_id)
            }
            covered = await self._covered(uow, ctx)
        refs = [replace(r, in_list=r.institution_id in listed) for r in refs]
        found = await self._vectors.of_texts([r.prompt for r in refs])
        if found is None or len(found.vectors) != len(refs):
            return PromptMapView(build_map(refs, None, model=NO_MODEL), False, covered)
        return PromptMapView(
            build_map(refs, found.vectors, model=found.model), True, covered
        )

    async def fit(self, ctx: AdmissionContext, text: str) -> IdeaFit:
        """Score an idea against the prompts no essay or slot covers (AI consent)."""
        await self._gate.require(ctx, AI)
        text = text.strip()
        if not text or len(text) > IDEA_MAX:
            raise InvalidAnswerError(params={"question": "text"})
        async with self._uow() as uow:
            refs = [*common_app_refs(), *await uow.prompt_catalog.all()]
            covered = await self._covered(uow, ctx)
        refs = [r for r in refs if r.key not in covered]
        query = await self._vectors.of_query(text)
        found = await self._vectors.of_texts([r.prompt for r in refs])
        if (
            query is None
            or found is None
            or found.model != query.model
            or len(found.vectors) != len(refs)
        ):
            return IdeaFit(False, NO_MODEL, delta_for(NO_MODEL), ())
        delta = delta_for(query.model)
        scored = [
            PromptFit(r, round(d, 4), fit_score(d, delta))
            for r, v in zip(refs, found.vectors, strict=True)
            for d in (cosine_distance(query.values, v),)
        ]
        scored.sort(key=lambda f: (-f.score, f.distance, f.prompt.key))
        return IdeaFit(True, query.model, delta, tuple(scored[:FIT_LIMIT]))

    @staticmethod
    async def _covered(
        uow: AdmissionUnitOfWork, ctx: AdmissionContext
    ) -> frozenset[str]:
        """Keys of prompts an essay targets or a supplemental slot already holds."""
        keys = {
            t.key for e in await uow.essays.list_for(ctx.user_id) for t in e.targets
        }
        for s in await uow.slots.for_student(ctx.user_id):
            head, _, tail = s.slot.partition(":")
            if head == "supp" and tail.isdigit():
                keys.add(prompt_key(s.institution_id, int(tail)))
        return frozenset(keys)
