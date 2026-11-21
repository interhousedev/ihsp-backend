"""AI review of one activity or honor (§9.1): four graded dimensions and a rewrite."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any, Final
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.review_checks import (
    align_word_fit,
    canonical_metrics,
    clean_rewrite,
    delimit,
    input_hash,
    limits_for,
    looks_injected,
    nfc,
    numbers,
    plain,
    projected_only_numbers,
    rewrite_violation,
)
from app.modules.admission.application.review_prompts import (
    PROMPT_VERSION,
    SCHEMA_VERSION,
    render_prompt,
)
from app.modules.admission.application.review_rubric import (
    DIMENSIONS,
    PROJECTED_IMPACT_CAP,
    RUBRIC_VERSION,
    cap,
    overall_item,
    rubric_text,
)
from app.modules.admission.application.review_schema import (
    MAX_MISSING_FACTS,
    REVIEW_SCHEMA,
    REVIEW_SCHEMA_NAME,
    REWRITE_SCHEMA,
    REWRITE_SCHEMA_NAME,
    AiItemReview,
    AiRewrite,
)
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    ConsentRequiredError,
    QuotaExceededError,
    WordsNotSetError,
)
from app.modules.admission.domain.items import Item
from app.modules.admission.ports.ai import PromptSource, QuotaOf, StructuredAi
from app.modules.admission.ports.consent import AI, PurposeConsents
from app.modules.admission.ports.items import (
    FeedbackKind,
    Metric,
    ProfileWordsRef,
    SafetyFlag,
    StoredReview,
)
from app.modules.admission.ports.unit_of_work import AdmissionUnitOfWork, UowFactory
from app.shared.ai_tasks import AiTask
from app.shared.clock import TASHKENT, Clock
from app.shared.contracts.ai import AiInvalidOutputError
from app.shared.ids import new_id
from app.shared.notifications import NotificationDraft, NotificationType

from pydantic import ValidationError

TARGET_KIND: Final = "item"
PER_ITEM_PER_DAY: Final = 10
REVIEW_TOKENS: Final = 2000
REWRITE_TOKENS: Final = 600
NOTE_MAX: Final = 500


@dataclass(frozen=True, slots=True)
class ItemInput:
    """Everything a model call about one item needs."""

    item: Item
    metrics: list[Metric]
    words: ProfileWordsRef


async def owned_item(
    access: AccessPolicy, uow: AdmissionUnitOfWork, ctx: AdmissionContext, item_id: UUID
) -> Item:
    """Return the caller's own item; a foreign or missing one is not found."""
    item = await uow.items.get(item_id)
    if item is None or item.student_id != ctx.user_id:
        raise AdmissionNotFoundError()
    res = await access.resolve(ctx, ctx.user_id)
    if not res.owner:
        raise AdmissionForbiddenError(params={"permission": "activities:edit"})
    return item


def review_hash(
    item: Item, metrics: Sequence[Metric], words: ProfileWordsRef, locale: str
) -> str:
    """Return the cache key of a review of this exact input."""
    return input_hash(
        {
            "task": AiTask.ADMIT_ITEM_REVIEW.value,
            "student_id": str(item.student_id),
            "target_kind": TARGET_KIND,
            "target_id": str(item.id),
            "versions": [PROMPT_VERSION, RUBRIC_VERSION, SCHEMA_VERSION],
            "locale": locale,
            "item": {
                "kind": item.kind,
                "position": nfc(item.title),
                "org": nfc(item.organization),
                "description": nfc(item.description),
                "category": item.category,
                "level": item.level,
                "grades": list(item.grades),
                "hours": item.hours_per_week,
                "weeks": item.weeks_per_year,
            },
            "metrics": canonical_metrics(metrics),
            "words": [nfc(w) for w in words.words],
            "words_version": words.version,
        }
    )


def caps_of(kind: str) -> dict[str, int]:
    """Return the character caps as prompt values."""
    position_max, org_max, description_max = limits_for(kind)
    return {
        "position_max": position_max,
        "org_max": org_max,
        "description_max": description_max,
    }


async def fix_rewrite(
    ai: StructuredAi,
    prompts: PromptSource,
    data: ItemInput,
    rewrite: AiRewrite,
    locale: str,
) -> AiRewrite | None:
    """Return an acceptable rewrite: as is, after one fix call, or None."""
    rewrite = clean_rewrite(rewrite, data.metrics)
    violation = rewrite_violation(rewrite, data.item, data.metrics)
    if violation is None:
        return rewrite
    system = await render_prompt(
        prompts,
        AiTask.ADMIT_ITEM_REWRITE_FIX,
        "system",
        locale,
        kind=data.item.kind,
        violation=violation,
        **caps_of(data.item.kind),
    )
    user = (
        delimit(data.item, data.metrics, strict=True)
        + "\n<rewrite>\n"
        + rewrite.model_dump_json()
        + "\n</rewrite>"
    )
    try:
        raw, _ = await ai.json(
            task=AiTask.ADMIT_ITEM_REWRITE_FIX,
            system=system,
            user=user,
            schema_name=REWRITE_SCHEMA_NAME,
            schema=REWRITE_SCHEMA,
            max_tokens=REWRITE_TOKENS,
        )
        fixed = clean_rewrite(AiRewrite.model_validate(raw), data.metrics)
    except (ValidationError, AiInvalidOutputError):
        return None
    if rewrite_violation(fixed, data.item, data.metrics) is not None:
        return None
    return fixed


def day_start(now: datetime) -> datetime:
    """Return the start of the Tashkent day of `now`."""
    local = now.astimezone(TASHKENT)
    return datetime.combine(local.date(), time.min, TASHKENT)


async def require_ai_consent(consents: PurposeConsents, student_id: UUID) -> None:
    """Refuse a model call on student content without the `admission_ai` consent."""
    granted = (await consents.granted([student_id])).get(student_id, frozenset())
    if AI not in granted:
        raise ConsentRequiredError(params={"purpose": AI})


class ItemReviewService:
    """Review an item, cache by input, and take the student's feedback."""

    def __init__(
        self,
        uow_factory: UowFactory,
        access: AccessPolicy,
        ai: StructuredAi,
        consents: PurposeConsents,
        clock: Clock,
        prompts: PromptSource,
        *,
        per_day: QuotaOf,
        per_item: int = PER_ITEM_PER_DAY,
    ) -> None:
        """Keep the collaborators and the soft limits."""
        self._uow = uow_factory
        self._access = access
        self._ai = ai
        self._consents = consents
        self._clock = clock
        self._prompts = prompts
        self._per_day = per_day
        self._per_item = per_item

    async def review(
        self, ctx: AdmissionContext, item_id: UUID, locale: str
    ) -> StoredReview:
        """Return the cached review of this input, or ask the model for a new one."""
        async with self._uow() as uow:
            item = await owned_item(self._access, uow, ctx, item_id)
            await require_ai_consent(self._consents, item.student_id)
            metrics = (await uow.items.metrics_for([item.id])).get(item.id, [])
            words = await uow.items.words(item.student_id)
            if words is None or not words.words:
                raise WordsNotSetError()
            digest = review_hash(item, metrics, words, locale)
            cached = await uow.items.find_review(TARGET_KIND, item.id, digest)
            if cached is not None and cached.status == "ready":
                return cached
            await self._check_quota(uow, item.student_id, item.id)
        data = ItemInput(item, metrics, words)
        review = await self._ask(data, digest, locale)
        async with self._uow() as uow:
            stored = await uow.items.add_review(review)
            uow.notify(
                NotificationDraft(
                    user_id=item.student_id,
                    type=NotificationType.ADMISSION_REVIEW_READY,
                    payload={
                        "title": item.title,
                        "path": f"/items/view/?id={item.id}",
                    },
                    dedupe_key=f"review:{stored.id}",
                )
            )
            await uow.commit()
        return stored

    async def _check_quota(
        self, uow: AdmissionUnitOfWork, student_id: UUID, item_id: UUID
    ) -> None:
        now = self._clock.now()
        task = AiTask.ADMIT_ITEM_REVIEW.value
        today = await uow.items.count_reviews(
            student_id, task, day_start(now), target_id=None
        )
        per_day = await self._per_day(student_id)
        if per_day is not None and today >= per_day:
            raise QuotaExceededError(
                params={"task": task, "limit": per_day, "period": "day"}
            )
        this_item = await uow.items.count_reviews(
            student_id, task, now - timedelta(days=1), target_id=item_id
        )
        if this_item >= self._per_item:
            raise QuotaExceededError(
                params={"task": task, "limit": self._per_item, "period": "day"}
            )

    async def _call(
        self, data: ItemInput, locale: str, *, strict: bool
    ) -> tuple[AiItemReview, str]:
        item = data.item
        system = await render_prompt(
            self._prompts,
            AiTask.ADMIT_ITEM_REVIEW,
            "system",
            locale,
            kind=item.kind,
            rubric=rubric_text(item.kind),
            **caps_of(item.kind),
        )
        if strict:
            system += "\n" + await render_prompt(
                self._prompts, AiTask.ADMIT_ITEM_REVIEW, "strict", locale
            )
        user = (
            "words: "
            + ", ".join(data.words.words)
            + "\n"
            + delimit(item, data.metrics, strict=strict)
        )
        raw, model = await self._ai.json(
            task=AiTask.ADMIT_ITEM_REVIEW,
            system=system,
            user=user,
            schema_name=REVIEW_SCHEMA_NAME,
            schema=REVIEW_SCHEMA,
            max_tokens=REVIEW_TOKENS,
        )
        try:
            return AiItemReview.model_validate(raw), model
        except ValidationError as exc:
            raise AiInvalidOutputError(support_details=str(exc)) from exc

    async def _ask(self, data: ItemInput, digest: str, locale: str) -> StoredReview:
        flag: SafetyFlag = "none"
        suspected = looks_injected(data.item)
        parsed, model = await self._call(data, locale, strict=suspected)
        if parsed.injection_suspected and not suspected:
            parsed, model = await self._call(data, locale, strict=True)
            suspected = True
        if suspected or parsed.injection_suspected:
            flag = "injection_suspected"
        base: dict[str, Any] = {
            "id": new_id(),
            "student_id": data.item.student_id,
            "target_kind": TARGET_KIND,
            "target_id": data.item.id,
            "input_hash": digest,
            "task": AiTask.ADMIT_ITEM_REVIEW.value,
            "model": model,
            "prompt_version": PROMPT_VERSION,
            "rubric_version": RUBRIC_VERSION,
            "schema_version": SCHEMA_VERSION,
            "words_version": data.words.version,
            "status": "ready",
        }
        if parsed.safeguarding:
            return StoredReview(
                **base,
                grades={},
                overall=None,
                payload={"message_key": "admission-safeguarding-support"},
                safety_flag="safeguarding",
            )
        dims = {d.dim: d for d in parsed.dimensions}
        if set(dims) != set(DIMENSIONS):
            raise AiInvalidOutputError(
                support_details="the review must grade the four dimensions"
            )
        planned = projected_only_numbers(data.item, data.metrics)
        impact = dims["impact"]
        cited = numbers(impact.evidence)
        if cited and cited <= planned:
            dims["impact"] = impact.model_copy(
                update={"grade": cap(impact.grade, PROJECTED_IMPACT_CAP)}
            )
        grades: dict[str, Any] = {d: dims[d].grade for d in DIMENSIONS}
        rewrite = await fix_rewrite(
            self._ai, self._prompts, data, parsed.rewrite, locale
        )
        payload = {
            "dimensions": [
                {
                    "dim": d,
                    "grade": dims[d].grade,
                    "evidence": plain(dims[d].evidence),
                    "suggestion": plain(dims[d].suggestion),
                }
                for d in DIMENSIONS
            ],
            "word_fit": [
                f.model_dump()
                for f in align_word_fit(parsed.word_fit, data.words.words)
            ],
            "rewrite": rewrite.model_dump() if rewrite else None,
            "missing_facts": [plain(f) for f in parsed.missing_facts][
                :MAX_MISSING_FACTS
            ],
        }
        return StoredReview(
            **base,
            grades=grades,
            overall=overall_item(grades),
            payload=payload,
            safety_flag=flag,
        )

    async def feedback(
        self,
        ctx: AdmissionContext,
        review_id: UUID,
        kind: FeedbackKind,
        note: str | None,
    ) -> None:
        """Store the student's reaction to their own review."""
        async with self._uow() as uow:
            review = await uow.items.get_review(review_id)
            if review is None or review.student_id != ctx.user_id:
                raise AdmissionNotFoundError()
            res = await self._access.resolve(ctx, ctx.user_id)
            if not res.owner:
                raise AdmissionForbiddenError(params={"permission": "activities:edit"})
            text = nfc(note.strip())[:NOTE_MAX] if note else None
            await uow.items.add_feedback(review_id, ctx.user_id, kind, text or None)
            await uow.commit()
