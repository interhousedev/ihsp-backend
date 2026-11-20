"""AI plan of saved opportunities over the school grades; needs AI consent."""

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.items import items_summary
from app.modules.admission.application.opportunities import (
    OpportunityService,
    PlanView,
)
from app.modules.admission.application.review_checks import nfc
from app.modules.admission.application.words import answer_texts, delimit, plain
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    ConsentRequiredError,
)
from app.modules.admission.domain.opportunities import GRADES, term_of
from app.modules.admission.infrastructure.ai.prompts import opportunity_plan as prompt
from app.modules.admission.ports.ai import PromptSource, QuotaOf, StructuredAi
from app.modules.admission.ports.consent import AI, PurposeConsents
from app.modules.admission.ports.unit_of_work import UowFactory
from app.shared.ai_tasks import AiTask
from app.shared.base_error import ValidationFailedError
from app.shared.brand import with_brand
from app.shared.clock import Clock
from app.shared.rate_limit import RateLimiter

_WEEK: Final = 7 * 24 * 3600
_TOKENS: Final = 2000
_TERMS: Final = ("fall", "spring", "summer")
_TEXT_MAX: Final = 200


@dataclass(frozen=True, slots=True)
class AiPlanStep:
    """A saved entry placed in a grade and term."""

    opportunity_id: UUID
    grade: int
    term: str
    why: str


@dataclass(frozen=True, slots=True)
class AiPlanConflict:
    """Two entries that clash."""

    first_id: UUID
    second_id: UUID
    reason: str


@dataclass(frozen=True, slots=True)
class AiPlanDeadline:
    """A deadline not to miss."""

    opportunity_id: UUID
    note: str


@dataclass(frozen=True, slots=True)
class AiPlan:
    """The cleaned plan as stored."""

    steps: list[AiPlanStep]
    conflicts: list[AiPlanConflict]
    deadlines: list[AiPlanDeadline]
    notes: list[str]
    created_at: dt.datetime

    def to_json(self) -> dict[str, Any]:
        """Stored form."""
        return {
            "steps": [
                {
                    "opportunity_id": str(s.opportunity_id),
                    "grade": s.grade,
                    "term": s.term,
                    "why": s.why,
                }
                for s in self.steps
            ],
            "conflicts": [
                {
                    "first_id": str(c.first_id),
                    "second_id": str(c.second_id),
                    "reason": c.reason,
                }
                for c in self.conflicts
            ],
            "deadlines": [
                {"opportunity_id": str(d.opportunity_id), "note": d.note}
                for d in self.deadlines
            ],
            "notes": self.notes,
        }


def _text(value: Any) -> str:
    return nfc(plain(str(value or ""))).strip()[:_TEXT_MAX]


def clean_plan(
    data: dict[str, Any],
    known: set[str],
    grade_now: int,
    at: dt.datetime,
    grades: Sequence[int] = GRADES,
) -> AiPlan:
    """Keep known ids, grades from now to the last school grade, valid terms."""
    first = max(min(grade_now, grades[-1]), grades[0])
    steps: list[AiPlanStep] = []
    placed: set[str] = set()
    for raw in list(data.get("steps") or [])[: prompt.MAX_STEPS]:
        ref = str(raw.get("opportunity_id", "")).strip()
        if ref not in known or ref in placed:
            continue
        try:
            grade = int(raw.get("grade", first))
        except (TypeError, ValueError):
            grade = first
        term = str(raw.get("term", "")).strip().lower()
        placed.add(ref)
        steps.append(
            AiPlanStep(
                UUID(ref),
                min(max(grade, first), grades[-1]),
                term if term in _TERMS else _TERMS[0],
                _text(raw.get("why")),
            )
        )
    steps.sort(key=lambda s: (s.grade, _TERMS.index(s.term)))
    conflicts = [
        AiPlanConflict(UUID(a), UUID(b), _text(raw.get("reason")))
        for raw in list(data.get("conflicts") or [])[: prompt.MAX_STEPS]
        if (a := str(raw.get("first_id", "")).strip()) in known
        and (b := str(raw.get("second_id", "")).strip()) in known
        and a != b
    ]
    seen: set[str] = set()
    deadlines: list[AiPlanDeadline] = []
    for raw in list(data.get("deadlines") or [])[: prompt.MAX_STEPS]:
        ref = str(raw.get("opportunity_id", "")).strip()
        if ref in known and ref not in seen:
            seen.add(ref)
            deadlines.append(AiPlanDeadline(UUID(ref), _text(raw.get("note"))))
    notes = [t for n in list(data.get("notes") or []) if (t := _text(n))]
    return AiPlan(steps, conflicts, deadlines, notes[: prompt.MAX_NOTES], at)


def plan_from_json(data: dict[str, Any], at: dt.datetime) -> AiPlan:
    """Read a stored plan (already clean)."""
    known = {
        str(s.get(k))
        for s in [
            *(data.get("steps") or []),
            *(data.get("conflicts") or []),
            *(data.get("deadlines") or []),
        ]
        for k in ("opportunity_id", "first_id", "second_id")
        if s.get(k)
    }
    return clean_plan(data, known, GRADES[0], at)


def _profile_lines(
    grade: int,
    locale: str,
    interests: str,
    career: str,
    words: Any,
    profile: Any,
) -> list[str]:
    lines = [f"Grade now: {grade}", f"Language: {locale}"]
    if interests.strip():
        lines.append(f"Interests: {interests.strip()}")
    if career.strip():
        lines.append(f"Career: {career.strip()}")
    if words is not None and words.words:
        lines.append(f"Spike: {', '.join(words.words)}")
    if profile is not None:
        lines += [f"[answer:{k}] {v}" for k, v in answer_texts(profile.answers).items()]
    return lines


def place_rest(
    plan: AiPlan, view: PlanView, grade_now: int, grades: Sequence[int] = GRADES
) -> AiPlan:
    """Place saved entries the model left out.

    The planned grade, else the first recommended grade from now, in the term of
    the next dated event; always inside the school grades.
    """
    first = max(min(grade_now, grades[-1]), grades[0])
    placed = {s.opportunity_id for s in plan.steps}
    extra: list[AiPlanStep] = []
    for e in view.entries:
        o = view.catalog.get(e.opportunity_id)
        if o is None or o.id in placed:
            continue
        fits = [g for g in o.draft.grades if g >= first]
        grade = e.planned_grade or (fits[0] if fits else first)
        days = sorted(d.day for d in view.deadlines if d.opportunity_id == o.id)
        term = term_of(days[0]) if days else _TERMS[0]
        extra.append(AiPlanStep(o.id, min(max(grade, first), grades[-1]), term, ""))
    if not extra:
        return plan
    steps = sorted([*plan.steps, *extra], key=lambda s: (s.grade, _TERMS.index(s.term)))
    return AiPlan(steps, plan.conflicts, plan.deadlines, plan.notes, plan.created_at)


class OpportunityPlanner:
    """Ask the model to place the saved entries over the remaining grades."""

    def __init__(
        self,
        uow_factory: UowFactory,
        access: AccessPolicy,
        catalog: OpportunityService,
        ai: StructuredAi,
        consents: PurposeConsents,
        clock: Clock,
        limiter: RateLimiter,
        weekly_limit: QuotaOf,
        prompts: PromptSource,
    ) -> None:
        """Keep the collaborators and the reader of the soft weekly limit."""
        self._uow = uow_factory
        self._access = access
        self._catalog = catalog
        self._ai = ai
        self._consents = consents
        self._clock = clock
        self._limiter = limiter
        self._limit = weekly_limit
        self._prompts = prompts

    async def _owner(self, ctx: AdmissionContext) -> None:
        res = await self._access.resolve(ctx, ctx.user_id)
        if not res.owner or not ctx.admission.is_applicant:
            raise AdmissionForbiddenError(params={"permission": "list:edit"})

    async def last(self, ctx: AdmissionContext) -> AiPlan | None:
        """The caller's stored plan."""
        await self._owner(ctx)
        async with self._uow() as uow:
            row = await uow.opportunities.ai_plan(ctx.user_id)
        return plan_from_json(*row) if row else None

    def _entry_lines(self, view: PlanView) -> list[str]:
        lines: list[str] = []
        for e in view.entries:
            o = view.catalog.get(e.opportunity_id)
            if o is None:
                continue
            d = o.draft
            dates = ", ".join(
                f"{ev.kind} {ev.day.isoformat()}"
                + (" (expected)" if ev.projected else "")
                for ev in self._catalog.upcoming(o)[:6]
            )
            lines.append(
                f"[entry:{o.id}] {d.kind}: {d.title}; grades "
                f"{', '.join(map(str, d.grades)) or 'any'}; planned grade "
                f"{e.planned_grade or 'none'}; dates {dates or 'none'}"
            )
        return lines

    async def generate(
        self, ctx: AdmissionContext, locale: str, *, interests: str, career: str
    ) -> AiPlan:
        """Build, clean and store a new plan of the caller's saved entries."""
        await self._owner(ctx)
        if len(interests) > 500 or len(career) > 300:
            raise ValidationFailedError(params={"field": "interests"})
        granted = (await self._consents.granted([ctx.user_id])).get(
            ctx.user_id, frozenset()
        )
        if AI not in granted:
            raise ConsentRequiredError(params={"purpose": AI})
        view = await self._catalog.plan_of(ctx, ctx.user_id)
        if not view.entries:
            raise ValidationFailedError(params={"field": "plan"})
        async with self._uow() as uow:
            words = await uow.items.words(ctx.user_id)
            items = await uow.items.list_for(ctx.user_id)
            metrics = await uow.items.metrics_for([i.id for i in items])
            profile = await uow.profiles.get(ctx.user_id)
        limit = await self._limit(ctx.user_id)
        if limit is not None:
            await self._limiter.hit(
                f"admission:opportunity_plan:{ctx.user_id}",
                limit=limit,
                window_seconds=_WEEK,
            )
        grades = await self._access.school_grades()
        grade = ctx.grade or grades[0]
        lines = _profile_lines(grade, locale, interests, career, words, profile)
        lines += [f"[activity] {i}" for i in items_summary(items, metrics)]
        lines += self._entry_lines(view)
        data, _ = await self._ai.json(
            task=AiTask.ADMIT_OPPORTUNITY_PLAN,
            system=with_brand(
                await self._prompts.text(
                    AiTask.ADMIT_OPPORTUNITY_PLAN, "system", locale
                )
            ),
            user=delimit(lines),
            schema_name=prompt.SCHEMA_NAME,
            schema=prompt.SCHEMA,
            max_tokens=_TOKENS,
        )
        known = {str(e.opportunity_id) for e in view.entries}
        plan = place_rest(
            clean_plan(data, known, grade, self._clock.now(), grades),
            view,
            grade,
            grades,
        )
        async with self._uow() as uow:
            await uow.opportunities.save_ai_plan(
                ctx.user_id, plan.to_json(), plan.created_at
            )
            await uow.commit()
        return plan
