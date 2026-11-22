"""The prompt map and idea fit: which essay can answer which prompts.

Both read the catalog of supplemental prompts and its embeddings. A missing
embedding model only makes the answer "unavailable". The only model call is the
one-off naming of new prompt groups (public text, stored for everyone); an idea fit
is stored per idea and prompt-map version, so asking again costs nothing.
"""

import datetime as dt
import hashlib
from dataclasses import dataclass, replace
from typing import Final, Literal
from uuid import UUID

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.essay_due import (
    DueDate,
    application_dues,
    earliest,
)
from app.modules.admission.application.essay_group_labels import GroupLabeler
from app.modules.admission.application.essay_match import uses_common_app
from app.modules.admission.application.essay_prompts import FlowGate
from app.modules.admission.domain.errors import InvalidAnswerError
from app.modules.admission.domain.essay_categories import (
    Category,
    ShortAnswer,
    classify_group,
    is_university_specific,
)
from app.modules.admission.domain.essay_flow import (
    GroupLabel,
    PromptGroup,
    PromptMap,
    PromptRef,
    StoredIdeaFit,
    build_map,
    common_app_refs,
    cosine_distance,
    delta_for,
    fallback_label,
    fit_score,
    prompt_key,
)
from app.modules.admission.domain.essays import IDEA_MAX
from app.modules.admission.ports.consent import AI
from app.modules.admission.ports.essay_crypto import EssayCipher
from app.modules.admission.ports.essay_flow import PromptVectors
from app.modules.admission.ports.unit_of_work import AdmissionUnitOfWork, UowFactory

FIT_LIMIT: Final = 20
NO_MODEL: Final = "none"
_PURPOSE: Final = "essay_idea_fit"
Scope = Literal["list", "all"]


@dataclass(frozen=True, slots=True)
class GroupView:
    """A group with its name and what the student has and owes for it."""

    group: PromptGroup
    label: str
    essay_ids: tuple[UUID, ...]
    in_list_count: int
    due_utc: dt.datetime | None
    due_predicted: bool
    category: Category = "other"
    short_answers: tuple[ShortAnswer, ...] = ()
    """The student's short texts for member prompts; only in `short_answer` groups."""


@dataclass(frozen=True, slots=True)
class PromptMapView:
    """The map, whether vectors were available, and the keys the student covered."""

    map: PromptMap
    available: bool
    covered: frozenset[str]
    groups: tuple[GroupView, ...] = ()
    """The groups of the requested scope, in map order, with their labels."""


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
    cached: bool = False
    """Served from the store; no model was called."""
    pending: bool = False
    """Cache-only ask with nothing stored yet."""


class EssayPromptMap:
    """Prompt map of the catalog and idea fit against uncovered prompts."""

    def __init__(
        self,
        uow_factory: UowFactory,
        gate: FlowGate,
        vectors: PromptVectors,
        cipher: EssayCipher,
        labeler: GroupLabeler | None = None,
    ) -> None:
        """Keep the collaborators; without a labeler groups get a plain fallback."""
        self._uow = uow_factory
        self._gate = gate
        self._vectors = vectors
        self._cipher = cipher
        self._labeler = labeler

    async def prompt_map(
        self, ctx: AdmissionContext, scope: Scope = "all", locale: str = "en"
    ) -> PromptMapView:
        """Group every prompt (Common App and supplements); mark the listed ones.

        `scope="list"` keeps the groups with a prompt of a listed university and
        the Common App groups.
        """
        await self._gate.owner(ctx)
        async with self._uow() as uow:
            listed = {
                e.institution_id for e in await uow.shortlist.entries(ctx.user_id)
            }
            # Common App prompts only matter when a listed university takes it.
            common = not listed
            for iid in listed:
                inst = await uow.catalog.institution(iid)
                if inst is not None and uses_common_app(inst):
                    common = True
                    break
            catalog = await uow.prompt_catalog.all()
            refs = [*(common_app_refs() if common else []), *catalog]
            covered = await self._covered(uow, ctx)
            dues = await application_dues(uow, ctx.user_id)
            essays = await uow.essays.list_for(ctx.user_id)
            answers = {
                a.prompt_key: a
                for a in await uow.short_answers.for_student(ctx.user_id)
            }
        refs = [replace(r, in_list=r.institution_id in listed) for r in refs]
        found = await self._vectors.of_texts([r.prompt for r in refs])
        available = found is not None and len(found.vectors) == len(refs)
        if found is None or not available:
            pmap = build_map(refs, None, model=NO_MODEL, isolate=is_university_specific)
        else:
            pmap = build_map(
                refs, found.vectors, model=found.model, isolate=is_university_specific
            )
        groups = [
            g
            for g in pmap.groups
            if scope == "all"
            or any(p.in_list or p.institution_id is None for p in g.prompts)
        ]
        labels = await self._labeler.labels(groups) if self._labeler else {}
        by_key: dict[str, list[UUID]] = {}
        for e in essays:
            for t in e.targets:
                by_key.setdefault(t.key, []).append(e.id)
        views = tuple(
            self._view(g, labels, by_key, dues, locale, answers) for g in groups
        )
        return PromptMapView(pmap, available, covered, views)

    @staticmethod
    def _view(
        g: PromptGroup,
        labels: dict[str, GroupLabel],
        by_key: dict[str, list[UUID]],
        dues: dict[UUID, DueDate],
        locale: str,
        answers: dict[str, ShortAnswer],
    ) -> GroupView:
        ids = dict.fromkeys(i for p in g.prompts for i in by_key.get(p.key, ()))
        institutions = {
            p.institution_id for p in g.prompts if p.in_list and p.institution_id
        }
        due = earliest([dues[i] for i in institutions if i in dues])
        label = labels.get(g.key)
        category = classify_group(
            g.prompts, "" if label is None else f"{label.en}\n{label.ru}\n{label.uz}"
        )
        return GroupView(
            g,
            label.of(locale) if label is not None else fallback_label(g.prompts),
            tuple(ids),
            len(institutions),
            None if due is None else due.due_utc,
            due is not None and due.predicted,
            category,
            tuple(
                answers[p.key]
                for p in g.prompts
                if category == "short_answer" and p.key in answers
            ),
        )

    async def fit(
        self, ctx: AdmissionContext, text: str, *, cached_only: bool = False
    ) -> IdeaFit:
        """Score an idea against the prompts no essay or slot covers (AI consent).

        The result is stored per idea text and prompt-map version (the uncovered
        prompts); an unchanged ask is served from the store. With `cached_only` a
        miss returns `pending` instead of calling the embedding model.
        """
        await self._gate.require(ctx, AI)
        text = text.strip()
        if not text or len(text) > IDEA_MAX:
            raise InvalidAnswerError(params={"question": "text"})
        async with self._uow() as uow:
            refs = [*common_app_refs(), *await uow.prompt_catalog.all()]
            covered = await self._covered(uow, ctx)
            refs = [r for r in refs if r.key not in covered]
            digest = await self._cipher.digest(ctx.user_id, _PURPOSE, text)
            version = _version(refs)
            stored = await uow.idea_fits.get(ctx.user_id, digest)
        if stored is not None and stored.version == version:
            return _from_stored(stored, refs)
        if cached_only:
            return IdeaFit(True, NO_MODEL, delta_for(NO_MODEL), (), pending=True)
        fit = await self._score(text, refs)
        if fit.available:
            async with self._uow() as uow:
                await uow.idea_fits.put(
                    ctx.user_id,
                    digest,
                    StoredIdeaFit(
                        version,
                        True,
                        fit.model,
                        fit.delta,
                        tuple((f.prompt.key, f.distance, f.score) for f in fit.items),
                    ),
                )
                await uow.commit()
        return fit

    async def _score(self, text: str, refs: list[PromptRef]) -> IdeaFit:
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


def _version(refs: list[PromptRef]) -> str:
    """The prompt-map version an idea fit is valid for: the prompts it was scored on."""
    raw = "\n".join(sorted(f"{r.key}\t{r.prompt}" for r in refs))
    return hashlib.sha256(raw.encode()).hexdigest()


def _from_stored(stored: StoredIdeaFit, refs: list[PromptRef]) -> IdeaFit:
    by_key = {r.key: r for r in refs}
    items = tuple(
        PromptFit(by_key[k], d, sc) for k, d, sc in stored.items if k in by_key
    )
    return IdeaFit(stored.available, stored.model, stored.delta, items, cached=True)
