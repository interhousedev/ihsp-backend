"""AI drafts of career exploration: professions, majors fit, the spike.

Every call needs the owner's AI consent and counts against one weekly soft limit.
Only the student's own answers and items are sent; the drafts are stored in the
plan for the student to shortlist, choose or confirm.
"""

from dataclasses import replace
from typing import Any, Final
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.career import owner_plan
from app.modules.admission.application.items import items_summary
from app.modules.admission.application.profession_fill import (
    build_custom,
    field_vocabulary,
)
from app.modules.admission.application.review_checks import nfc
from app.modules.admission.application.student_context import student_block
from app.modules.admission.application.words import delimit, plain
from app.modules.admission.domain.career import (
    EVIDENCE_MAX,
    GAPS_MAX,
    PROFESSIONS_MAX,
    REASON_MAX,
    SUMMARY_MAX,
    TITLE_MAX,
    CareerPlan,
    MajorFit,
    Profession,
    Spike,
    SpikeEvidence,
    localized,
)
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    ConsentRequiredError,
)
from app.modules.admission.domain.professions import Profession as IscoProfession
from app.modules.admission.infrastructure.ai.prompts import career as prompt
from app.modules.admission.ports.ai import PromptSource, QuotaOf, StructuredAi
from app.modules.admission.ports.consent import AI, PurposeConsents
from app.modules.admission.ports.fit import ProfessionCatalog
from app.modules.admission.ports.student_search import StudentDataSearch
from app.modules.admission.ports.unit_of_work import AdmissionUnitOfWork, UowFactory
from app.shared.ai_tasks import AiTask
from app.shared.brand import with_brand
from app.shared.rate_limit import RateLimiter

_WEEK: Final = 7 * 24 * 3600
_TOKENS: Final = 1500
FIT_MAX: Final = 10


def _text(value: Any, limit: int) -> str:
    return nfc(plain(str(value or ""))).strip()[:limit]


def clean_professions(data: dict[str, Any]) -> list[Profession]:
    """Distinct plain professions, at most eight."""
    seen: set[str] = set()
    out: list[Profession] = []
    for raw in data.get("professions", []):
        title = _text(raw.get("title"), TITLE_MAX)
        if not title or title.casefold() in seen:
            continue
        seen.add(title.casefold())
        out.append(Profession(title, _text(raw.get("reason"), REASON_MAX)))
    return out[:PROFESSIONS_MAX]


def clean_fit(data: dict[str, Any], codes: set[str]) -> list[MajorFit]:
    """Known codes only, scores clamped, best first."""
    best: dict[str, MajorFit] = {}
    for raw in data.get("fit", []):
        code = str(raw.get("code", "")).strip().lower()
        if code not in codes or code in best:
            continue
        try:
            score = min(max(int(raw.get("score", 0)), 0), 100)
        except (TypeError, ValueError):
            score = 0
        best[code] = MajorFit(code, score, _text(raw.get("reason"), REASON_MAX))
    return sorted(best.values(), key=lambda f: -f.score)[:FIT_MAX]


def clean_spike(data: dict[str, Any], known: set[str]) -> Spike:
    """A draft spike; evidence only for the student's own listed items."""
    evidence: list[SpikeEvidence] = []
    for raw in data.get("evidence", []):
        ref = str(raw.get("item_id", "")).strip()
        if ref in known and all(str(e.item_id) != ref for e in evidence):
            evidence.append(
                SpikeEvidence(UUID(ref), _text(raw.get("note"), REASON_MAX))
            )
    gaps = [g for g in (_text(g, REASON_MAX) for g in data.get("gaps", [])) if g]
    return Spike(
        title=_text(data.get("title"), TITLE_MAX),
        summary=_text(data.get("summary"), SUMMARY_MAX),
        evidence=tuple(evidence[:EVIDENCE_MAX]),
        gaps=tuple(dict.fromkeys(gaps))[:GAPS_MAX],
    )


class CareerSuggester:
    """Ask the model for career drafts; the owner needs AI consent and a quota."""

    def __init__(
        self,
        uow_factory: UowFactory,
        access: AccessPolicy,
        ai: StructuredAi,
        consents: PurposeConsents,
        limiter: RateLimiter,
        weekly_limit: QuotaOf,
        prompts: PromptSource,
        search: StudentDataSearch | None = None,
        professions: ProfessionCatalog | None = None,
    ) -> None:
        """Keep the collaborators and the reader of the soft weekly limit."""
        self._catalog = professions
        self._uow = uow_factory
        self._access = access
        self._ai = ai
        self._consents = consents
        self._limiter = limiter
        self._limit = weekly_limit
        self._prompts = prompts
        self._search = search

    async def _guard(self, ctx: AdmissionContext) -> None:
        res = await self._access.resolve(ctx, ctx.user_id)
        if not res.owner:
            raise AdmissionForbiddenError(params={"permission": "activities:edit"})
        granted = (await self._consents.granted([ctx.user_id])).get(
            ctx.user_id, frozenset()
        )
        if AI not in granted:
            raise ConsentRequiredError(params={"purpose": AI})

    async def _ask(
        self,
        ctx: AdmissionContext,
        task: AiTask,
        lines: list[str],
        schema: tuple[str, dict[str, Any]],
        locale: str,
    ) -> dict[str, Any]:
        limit = await self._limit(ctx.user_id)
        if limit is not None:
            await self._limiter.hit(
                f"admission:career:{ctx.user_id}", limit=limit, window_seconds=_WEEK
            )
        name, body = schema
        data, _ = await self._ai.json(
            task=task,
            system=with_brand(await self._prompts.text(task, "system", locale)),
            user=delimit(lines),
            schema_name=name,
            schema=body,
            max_tokens=_TOKENS,
        )
        return data if isinstance(data, dict) else {}

    async def _context(
        self, uow: AdmissionUnitOfWork, plan: CareerPlan, locale: str
    ) -> tuple[list[str], set[str]]:
        """The student's answers and items as delimited lines, and the item ids."""
        questions = {
            str(q.id): q for q in await uow.career.questions(active_only=False)
        }
        items = await uow.items.list_for(plan.student_id)
        metrics = await uow.items.metrics_for([i.id for i in items])
        summary = items_summary(items, metrics)
        lines = [f"Language: {locale}"]
        for qid, answer in plan.answers.items():
            question = questions.get(qid)
            if question is not None:
                lines.append(
                    f"[{question.section}] {localized(question.prompt, locale)}"
                )
                lines.append(f"Answer: {answer}")
        lines += [f"[item:{i['id']}] {i}" for i in summary]
        lines += [f"[shortlisted] {p.title}" for p in plan.shortlist]
        ikigai = (await uow.profession_plans.get(plan.student_id)).ikigai
        for circle in ("love", "good_at", "needs", "paid"):
            lines += [f"[ikigai:{circle}] {chip}" for chip in getattr(ikigai, circle)]
        queries = [str(a) for a in plan.answers.values()][:2]
        queries += [p.title for p in plan.shortlist][:1]
        queries.append("interests and strengths")
        lines += await student_block(
            self._search,
            plan.student_id,
            queries,
            ("item", "course", "grade", "test_score", "profile", "career"),
        )
        return lines, {i["id"] for i in summary}

    async def professions(self, ctx: AdmissionContext, locale: str) -> CareerPlan:
        """Replace the suggestions; shortlisted professions stay."""
        await self._guard(ctx)
        async with self._uow() as uow:
            plan = await owner_plan(uow, ctx.user_id)
            lines, _ = await self._context(uow, plan, locale)
        data = await self._ask(
            ctx,
            AiTask.ADMIT_CAREER_PROFESSIONS,
            lines,
            (prompt.PROFESSIONS_SCHEMA_NAME, prompt.PROFESSIONS_SCHEMA),
            locale,
        )
        kept = plan.shortlist
        taken = {p.title.casefold() for p in kept}
        fresh = [p for p in clean_professions(data) if p.title.casefold() not in taken]
        return await self._store(
            ctx, plan, professions=(kept + fresh)[: PROFESSIONS_MAX + len(kept)]
        )

    async def profession_card(
        self, ctx: AdmissionContext, title: str, locale: str
    ) -> IscoProfession:
        """Draft the card of a typed-in profession; the caller stores it."""
        if self._catalog is None:
            raise AdmissionForbiddenError(params={"permission": "professions:fill"})
        await self._guard(ctx)
        lines = [f"Language: {locale}", f"[title] {title}"]
        lines += [f"[field] {f}" for f in field_vocabulary(self._catalog)]
        data = await self._ask(
            ctx,
            AiTask.ADMIT_PROFESSION_FILL,
            lines,
            (prompt.PROFESSION_FILL_SCHEMA_NAME, prompt.PROFESSION_FILL_SCHEMA),
            locale,
        )
        return build_custom(data, title, self._catalog)

    async def majors_fit(self, ctx: AdmissionContext, locale: str) -> CareerPlan:
        """Rank majors of the taxonomy for the student."""
        await self._guard(ctx)
        async with self._uow() as uow:
            plan = await owner_plan(uow, ctx.user_id)
            lines, _ = await self._context(uow, plan, locale)
            majors = await uow.career.majors(active_only=True)
        lines += [f"[major] {m.code}: {localized(m.name, 'en')}" for m in majors]
        data = await self._ask(
            ctx,
            AiTask.ADMIT_CAREER_MAJORS,
            lines,
            (prompt.MAJORS_SCHEMA_NAME, prompt.MAJORS_SCHEMA),
            locale,
        )
        return await self._store(
            ctx, plan, fit=clean_fit(data, {m.code for m in majors})
        )

    async def spike(self, ctx: AdmissionContext, locale: str) -> CareerPlan:
        """Draft an unconfirmed spike from the plan and the items."""
        await self._guard(ctx)
        async with self._uow() as uow:
            plan = await owner_plan(uow, ctx.user_id)
            lines, known = await self._context(uow, plan, locale)
        lines += [f"[major] {code}" for code in plan.majors]
        data = await self._ask(
            ctx,
            AiTask.ADMIT_CAREER_SPIKE,
            lines,
            (prompt.SPIKE_SCHEMA_NAME, prompt.SPIKE_SCHEMA),
            locale,
        )
        return await self._store(ctx, plan, spike=clean_spike(data, known))

    async def _store(
        self, ctx: AdmissionContext, plan: CareerPlan, **change: Any
    ) -> CareerPlan:
        async with self._uow() as uow:
            current = await owner_plan(uow, ctx.user_id)
            saved = await uow.career.save_plan(replace(current, **change))
            await uow.commit()
        return saved
