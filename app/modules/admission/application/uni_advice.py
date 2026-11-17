"""Per-university advice for a student: questions, academic and activity ideas.

The model reads the student's profile, scores, items and the university's facts.
The answer is stored per (student, locale, university) and reused for 14 days while
the student's data are unchanged; a fresh answer counts against the soft AI limit.
"""

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.review_checks import nfc
from app.modules.admission.application.words import delimit, plain
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
)
from app.modules.admission.domain.uni_chat import (
    ADVICE,
    is_fresh,
    render_brief,
    suggested_questions,
)
from app.modules.admission.infrastructure.ai.prompts import uni_advice as prompt
from app.modules.admission.ports.ai import PromptSource, QuotaOf, StructuredAi
from app.modules.admission.ports.assistant import AssistantData
from app.modules.admission.ports.consent import AI, PurposeConsents
from app.modules.admission.ports.uni_chat import UniChatRepository
from app.modules.admission.ports.unit_of_work import UowFactory
from app.shared.ai_tasks import AiTask
from app.shared.brand import with_brand
from app.shared.clock import Clock
from app.shared.rate_limit import RateLimiter

_WEEK: Final = 7 * 24 * 3600
_TOKENS: Final = 1500
_QUESTIONS: Final = 5
_ITEMS: Final = 4


@dataclass(frozen=True, slots=True)
class AdviceItem:
    """A titled suggestion."""

    title: str
    detail: str


@dataclass(frozen=True, slots=True)
class UniAdvice:
    """What a student may ask, study and do for one university."""

    questions: list[str]
    academic: list[AdviceItem]
    activities: list[AdviceItem]


def _text(value: Any, limit: int) -> str:
    return nfc(plain(str(value or ""))).strip()[:limit]


def _items(raw: Any) -> list[AdviceItem]:
    out: list[AdviceItem] = []
    for x in raw if isinstance(raw, list) else []:
        if not isinstance(x, dict):
            continue
        title, detail = _text(x.get("title"), 80), _text(x.get("detail"), 300)
        if title and detail:
            out.append(AdviceItem(title, detail))
    return out[:_ITEMS]


def clean_advice(data: dict[str, Any]) -> UniAdvice:
    """Plain, capped and de-duplicated advice."""
    questions: list[str] = []
    raw = data.get("questions")
    for q in raw if isinstance(raw, list) else []:
        text = _text(q, 200)
        if text and text.casefold() not in {x.casefold() for x in questions}:
            questions.append(text)
    return UniAdvice(
        questions[:_QUESTIONS],
        _items(data.get("academic")),
        _items(data.get("activities")),
    )


def _fingerprint(application: dict[str, Any]) -> str:
    body = json.dumps(application, sort_keys=True, default=str)
    return hashlib.sha256(body.encode()).hexdigest()


def _key(student_id: UUID, institution_id: UUID, locale: str) -> str:
    body = f"{student_id}:{institution_id}:{locale}"
    return hashlib.sha256(body.encode()).hexdigest()


def _dump(advice: UniAdvice) -> dict[str, Any]:
    return {
        "questions": advice.questions,
        "academic": [{"title": a.title, "detail": a.detail} for a in advice.academic],
        "activities": [
            {"title": a.title, "detail": a.detail} for a in advice.activities
        ],
    }


class UniAdviceService:
    """Advice for a student about one university; needs AI consent and a quota."""

    def __init__(
        self,
        uow_factory: UowFactory,
        access: AccessPolicy,
        consents: PurposeConsents,
        repo: UniChatRepository,
        data: AssistantData,
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
        self._ai = ai
        self._limiter = limiter
        self._limit = weekly_limit
        self._prompts = prompts
        self._clock = clock

    async def advice(
        self, ctx: AdmissionContext, institution_id: UUID, locale: str
    ) -> UniAdvice:
        """The student's advice; without AI consent only the common questions.

        Raises:
            AdmissionForbiddenError: The caller is not an applicant.
            AdmissionNotFoundError: Unknown university.
        """
        if not ctx.admission.is_applicant:
            raise AdmissionForbiddenError(params={"permission": "uni_chat:use"})
        res = await self._access.resolve(ctx, ctx.user_id)
        if not res.owner:
            raise AdmissionForbiddenError(params={"permission": "uni_chat:use"})
        async with self._uow() as uow:
            inst = await uow.catalog.institution(institution_id)
            if inst is None:
                raise AdmissionNotFoundError()
            found = await uow.catalog.scholarships(institution_id=institution_id)
            entry = await uow.shortlist.find(ctx.user_id, institution_id)
        granted = (await self._consents.granted([ctx.user_id])).get(
            ctx.user_id, frozenset()
        )
        if AI not in granted:
            return UniAdvice(suggested_questions(inst, len(found), locale), [], [])
        application = {
            "profile": await self._data.profile(ctx.user_id),
            "test_scores": await self._data.test_scores(ctx.user_id),
            "activities": await self._data.items(ctx.user_id),
        }
        fp = _fingerprint(application)
        key = _key(ctx.user_id, institution_id, locale)
        now = self._clock.now()
        hit = await self._repo.cached(ADVICE, key)
        if (
            hit is not None
            and is_fresh(hit.fetched_at, now)
            and hit.payload.get("fp") == fp
        ):
            return clean_advice(hit.payload)
        advice = await self._generate(
            ctx, render_brief(inst, found, entry, application), locale
        )
        await self._repo.store(ADVICE, key, {"fp": fp, **_dump(advice)}, now)
        return advice

    async def _generate(
        self,
        ctx: AdmissionContext,
        brief: str,
        locale: str,
    ) -> UniAdvice:
        limit = await self._limit(ctx.user_id)
        if limit is not None:
            await self._limiter.hit(
                f"admission:uni_advice:{ctx.user_id}",
                limit=limit,
                window_seconds=_WEEK,
            )
        data, _ = await self._ai.json(
            task=AiTask.ADMIT_UNI_ADVICE,
            system=with_brand(
                await self._prompts.text(AiTask.ADMIT_UNI_ADVICE, "system", locale)
            ),
            user=delimit([f"Language: {locale}", brief]),
            schema_name=prompt.SCHEMA_NAME,
            schema=prompt.SCHEMA,
            max_tokens=_TOKENS,
        )
        return clean_advice(data if isinstance(data, dict) else {})
