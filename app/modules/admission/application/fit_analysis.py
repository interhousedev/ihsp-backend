"""Quick, cheap AI read of one university's fit ring for the caller.

Input is a few compact `key: value` lines (axis scores, key facts, a trimmed
student summary, no essays); the answer corrects each axis a little and adds a
short text. It is cached by the hash of those lines, so an unchanged student and
university cost nothing, and a fresh answer counts against the soft AI limit.
"""

import hashlib
from dataclasses import dataclass
from typing import Any, Final, Mapping
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.fit import FitService
from app.modules.admission.application.review_checks import nfc
from app.modules.admission.application.words import delimit, plain
from app.modules.admission.domain.catalog_display import highlights
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
)
from app.modules.admission.domain.fit import AXES, AxisKey, FitResult, StudentFit
from app.modules.admission.infrastructure.ai.prompts import fit_analysis as prompt
from app.modules.admission.ports.ai import PromptSource, QuotaOf, StructuredAi
from app.modules.admission.ports.assistant import AssistantData
from app.modules.admission.ports.consent import AI, PurposeConsents
from app.modules.admission.ports.uni_chat import UniChatRepository
from app.modules.admission.ports.unit_of_work import UowFactory
from app.shared.ai_tasks import AiTask
from app.shared.brand import with_brand
from app.shared.clock import Clock
from app.shared.rate_limit import RateLimiter

KIND: Final = "fit_analysis"
_WEEK: Final = 7 * 24 * 3600
_TOKENS: Final = 350
_MAX_ADJUST: Final = 15
_FACTS: Final = 8
_ITEMS: Final = 5
_ANSWERS: Final = 10
_CELL: Final = 60


@dataclass(frozen=True, slots=True)
class FitAxisAnalysis:
    """An axis before and after the AI correction (`None` while unknown)."""

    key: AxisKey
    base_score: int | None
    score: int | None


@dataclass(frozen=True, slots=True)
class FitAnalysis:
    """The corrected ring and the short text."""

    base_total: int | None
    total: int | None
    known_share: float
    axes: tuple[FitAxisAnalysis, ...]
    strengths: tuple[str, ...]
    risks: tuple[str, ...]
    next_step: str
    ai: bool
    """False when the caller has not granted AI consent: rule-based values only."""


def _cut(value: Any, limit: int = _CELL) -> str:
    return nfc(plain(str(value if value is not None else ""))).strip()[:limit]


def _clamp(raw: Any) -> int:
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return 0
    return max(-_MAX_ADJUST, min(_MAX_ADJUST, n))


def _lines(raw: Any, limit: int, count: int) -> list[str]:
    out = [_cut(x, limit) for x in raw] if isinstance(raw, list) else []
    return [x for x in out if x][:count]


def adjusted_total(
    base: FitResult, adjust: Mapping[str, int]
) -> tuple[tuple[FitAxisAnalysis, ...], int | None]:
    """Axes with the clamped deltas on known axes, and the weighted total."""
    axes: list[FitAxisAnalysis] = []
    num = den = 0.0
    for a in base.axes:
        score = (
            None
            if a.score is None
            else max(0, min(100, a.score + adjust.get(a.key, 0)))
        )
        axes.append(FitAxisAnalysis(a.key, a.score, score))
        if score is not None:
            num += score * a.weight
            den += a.weight
    total = None if den == 0 else max(0, min(100, round(num / den)))
    return tuple(axes), total


def _answers(profile: dict[str, Any]) -> list[str]:
    out: list[str] = []
    answers = profile.get("answers")
    for k, v in (answers if isinstance(answers, dict) else {}).items():
        if isinstance(v, str | int | float) and not isinstance(v, bool) and v != "":
            out.append(f"{_cut(k, 30)}={_cut(v)}")
        if len(out) >= _ANSWERS:
            break
    return out


def _scores(rows: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for r in rows[:4]:
        name = r.get("label") or r.get("level") or "test"
        total = r.get("total")
        if isinstance(total, dict):
            total = total.get("value", total.get("score"))
        out.append(f"{_cut(name, 30)}={_cut(total, 20)}")
    return out


def _activities(rows: list[dict[str, Any]]) -> list[str]:
    ranked = sorted(rows, key=lambda r: not r.get("starred"))
    return [_cut(r.get("title"), 50) for r in ranked[:_ITEMS] if r.get("title")]


def compact_input(
    inst_name: str,
    facts: list[str],
    fit: FitResult,
    student: StudentFit,
    locale: str,
    profile: dict[str, Any],
    scores: list[dict[str, Any]],
    items: list[dict[str, Any]],
    words: tuple[str, ...],
    goals: list[str],
) -> str:
    """The few lines the model sees; also the cache identity."""
    axis = " ".join(
        f"{a.key}={'?' if a.score is None else a.score}(w{round(a.weight * 100)})"
        for a in fit.axes
    )
    rows = [
        f"uni: {_cut(inst_name, 80)}",
        f"axes: {axis}",
        f"facts: {'; '.join(facts)}",
        f"budget: {student.budget_band or '?'}",
        f"goals: {', '.join(goals) or '?'}",
        f"words: {', '.join(_cut(w, 24) for w in words) or '?'}",
        f"tests: {', '.join(_scores(scores)) or '?'}",
        f"profile: {', '.join(_answers(profile)) or '?'}",
        f"activities: {'; '.join(_activities(items)) or '?'}",
    ]
    return "\n".join(rows)


def _digest(text: str, locale: str) -> str:
    return hashlib.sha256(f"{locale}\n{text}".encode()).hexdigest()


class FitAnalysisService:
    """The fit ring of one university with the AI correction and a short text."""

    def __init__(
        self,
        uow_factory: UowFactory,
        access: AccessPolicy,
        consents: PurposeConsents,
        repo: UniChatRepository,
        data: AssistantData,
        fit: FitService,
        ai: StructuredAi,
        limiter: RateLimiter,
        weekly_limit: QuotaOf,
        prompts: PromptSource,
        clock: Clock,
    ) -> None:
        """Keep the collaborators."""
        self._uow = uow_factory
        self._access = access
        self._consents = consents
        self._repo = repo
        self._data = data
        self._fit = fit
        self._ai = ai
        self._limiter = limiter
        self._limit = weekly_limit
        self._prompts = prompts
        self._clock = clock

    async def analyse(
        self, ctx: AdmissionContext, institution_id: UUID, locale: str
    ) -> FitAnalysis:
        """Analyse the caller's fit; without AI consent the rule-based ring only.

        Raises:
            AdmissionForbiddenError: The caller is not an applicant.
            AdmissionNotFoundError: Unknown university.
            RateLimitExceededError: The soft AI limit is used up (fresh answers).
        """
        if not ctx.admission.is_applicant:
            raise AdmissionForbiddenError(params={"permission": "fit_analysis:use"})
        res = await self._access.resolve(ctx, ctx.user_id)
        if not res.owner:
            raise AdmissionForbiddenError(params={"permission": "fit_analysis:use"})
        async with self._uow() as uow:
            inst = await uow.catalog.institution(institution_id)
            words = await uow.profiles.get_words(ctx.user_id)
        if inst is None:
            raise AdmissionNotFoundError()
        now = self._clock.now()
        fit, student = await self._fit.detail(ctx, inst, locale, now.year)
        base = tuple(FitAxisAnalysis(a.key, a.score, a.score) for a in fit.axes)
        granted = (await self._consents.granted([ctx.user_id])).get(
            ctx.user_id, frozenset()
        )
        if AI not in granted:
            return FitAnalysis(
                fit.total, fit.total, fit.known_share, base, (), (), "", False
            )
        facts = [
            f"{h['label']}: {_cut(h['value_text'], 40)}"
            for h in highlights(inst, "en")[:_FACTS]
        ]
        goals = [p.name(locale) for p in student.professions[:3]]
        text = compact_input(
            inst.name,
            facts,
            fit,
            student,
            locale,
            await self._data.profile(ctx.user_id),
            await self._data.test_scores(ctx.user_id),
            await self._data.items(ctx.user_id),
            words.words if words is not None else (),
            goals,
        )
        key = _digest(text, locale)
        hit = await self._repo.cached(KIND, key)
        if hit is not None and hit.payload.get("v") == prompt.PROMPT_VERSION:
            data = hit.payload
        else:
            data = await self._generate(ctx, text, locale)
            await self._repo.store(KIND, key, {"v": prompt.PROMPT_VERSION, **data}, now)
        raw = data.get("adjust")
        adjust = raw if isinstance(raw, dict) else {}
        deltas: dict[str, int] = {k: _clamp(adjust.get(k)) for k in AXES}
        axes, total = adjusted_total(fit, deltas)
        return FitAnalysis(
            fit.total,
            total,
            fit.known_share,
            axes,
            tuple(_lines(data.get("strengths"), 120, 2)),
            tuple(_lines(data.get("risks"), 120, 2)),
            _cut(data.get("next_step"), 140),
            True,
        )

    async def _generate(
        self, ctx: AdmissionContext, text: str, locale: str
    ) -> dict[str, Any]:
        limit = await self._limit(ctx.user_id)
        if limit is not None:
            await self._limiter.hit(
                f"admission:fit_analysis:{ctx.user_id}",
                limit=limit,
                window_seconds=_WEEK,
            )
        data, _ = await self._ai.json(
            task=AiTask.ADMIT_FIT_ANALYSIS,
            system=with_brand(
                await self._prompts.text(AiTask.ADMIT_FIT_ANALYSIS, "system", locale)
            ),
            user=delimit([f"Language: {locale}", text]),
            schema_name=prompt.SCHEMA_NAME,
            schema=prompt.SCHEMA,
            max_tokens=_TOKENS,
        )
        d = data if isinstance(data, dict) else {}
        raw = d.get("adjust")
        adjust = raw if isinstance(raw, dict) else {}
        return {
            "adjust": {k: _clamp(adjust.get(k)) for k in AXES},
            "strengths": _lines(d.get("strengths"), 120, 2),
            "risks": _lines(d.get("risks"), 120, 2),
            "next_step": _cut(d.get("next_step"), 140),
        }
