"""Essay reviews: one base review per essay, one university review per choice.

The base review judges the writing and is shared by every university; each
university review judges the fit with that university's sourced goals. Each
result is stored sealed under a keyed digest of its input, so an unchanged
input is served without a model call and without spending quota.
"""

from dataclasses import dataclass
from typing import Final
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.essay_review_core import (
    base_from,
    base_payload,
    essay_input,
    input_key,
    load_uni_context,
    run_base_review,
    run_uni_review,
    uni_from,
    uni_lines,
    uni_payload,
    unsourced_review,
)
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    ConsentRequiredError,
    EssayTooShortError,
    ItemLimitError,
)
from app.modules.admission.domain.essay_reviews import (
    MAX_UNIVERSITIES,
    REVIEW_MIN_WORDS,
    BaseReview,
    EssayInput,
    ReviewKind,
    StoredReview,
    UniContext,
    UniReview,
)
from app.modules.admission.domain.essays import Essay, word_count
from app.modules.admission.domain.exemplars import ExemplarMatch
from app.modules.admission.infrastructure.ai.prompts import essay_review as review
from app.modules.admission.ports.ai import PromptSource, QuotaOf, StructuredAi
from app.modules.admission.ports.consent import AI, PurposeConsents
from app.modules.admission.ports.essay_crypto import EssayCipher
from app.modules.admission.ports.exemplars import ExemplarSource
from app.modules.admission.ports.unit_of_work import AdmissionUnitOfWork, UowFactory
from app.shared.ai_tasks import AiTask
from app.shared.clock import Clock
from app.shared.ids import new_id
from app.shared.rate_limit import RateLimiter

_WEEK: Final = 7 * 86400
_PURPOSE: Final = "essay_review"


@dataclass(frozen=True, slots=True)
class UniEntry:
    """The review for one university; `stale` when the input changed since."""

    institution_id: UUID
    name: str
    review: UniReview
    cached: bool
    stale: bool


@dataclass(frozen=True, slots=True)
class EssayReviews:
    """The base review and the university reviews of one essay."""

    base: BaseReview | None
    base_cached: bool
    base_stale: bool
    universities: tuple[UniEntry, ...]


def _base_key(
    essay: EssayInput, locale: str, matches: tuple[ExemplarMatch, ...]
) -> str:
    ids = sorted(str(m.exemplar.id) for m in matches)
    return input_key(
        "base",
        locale,
        essay.kind,
        essay.title,
        essay.prompt_text,
        str(essay.word_limit),
        essay.body,
        review.BASE,
        *ids,
    )


def _uni_key(essay: EssayInput, locale: str, uni: UniContext) -> str:
    return input_key(
        "uni",
        locale,
        essay.kind,
        essay.title,
        essay.prompt_text,
        str(essay.word_limit),
        essay.body,
        review.UNI,
        *uni_lines(uni),
    )


class EssayReviewService:
    """Runs and serves the stored base and university reviews of an essay."""

    def __init__(
        self,
        uow_factory: UowFactory,
        access: AccessPolicy,
        ai: StructuredAi,
        consents: PurposeConsents,
        clock: Clock,
        limiter: RateLimiter,
        base_quota: QuotaOf,
        uni_quota: QuotaOf,
        prompts: PromptSource,
        exemplars: ExemplarSource,
        cipher: EssayCipher,
    ) -> None:
        """Keep the collaborators and the readers of the soft weekly limits."""
        self._uow = uow_factory
        self._access = access
        self._ai = ai
        self._consents = consents
        self._clock = clock
        self._limiter = limiter
        self._base_quota = base_quota
        self._uni_quota = uni_quota
        self._prompts = prompts
        self._exemplars = exemplars
        self._cipher = cipher

    async def _owner(self, ctx: AdmissionContext) -> None:
        res = await self._access.resolve(ctx, ctx.user_id)
        if not res.owner:
            raise AdmissionForbiddenError(params={"permission": "essays:edit"})

    async def _gate(self, ctx: AdmissionContext) -> None:
        await self._owner(ctx)
        granted = (await self._consents.granted([ctx.user_id])).get(
            ctx.user_id, frozenset()
        )
        if AI not in granted:
            raise ConsentRequiredError(params={"purpose": AI})

    @staticmethod
    async def _essay(
        uow: AdmissionUnitOfWork, ctx: AdmissionContext, eid: UUID
    ) -> Essay:
        essay = await uow.essays.get(eid)
        if essay is None or essay.student_id != ctx.user_id:
            raise AdmissionNotFoundError()
        return essay

    async def _hit(self, quota: QuotaOf, name: str, uid: UUID) -> None:
        limit = await quota(uid)
        if limit is not None:
            await self._limiter.hit(
                f"admission:{name}:{uid}", limit=limit, window_seconds=_WEEK
            )

    async def _closest(self, essay: EssayInput) -> tuple[ExemplarMatch, ...]:
        return tuple(
            await self._exemplars.closest(
                kind=essay.kind,
                prompt=essay.prompt_text,
                body=essay.body,
                institution_id=None,
            )
        )

    async def _digest(self, uid: UUID, key: str) -> str:
        return await self._cipher.digest(uid, _PURPOSE, key)

    def _stored(
        self,
        essay: Essay,
        kind: ReviewKind,
        institution_id: UUID | None,
        digest: str,
        payload: dict[str, object],
        model: str,
        task: AiTask,
    ) -> StoredReview:
        return StoredReview(
            id=new_id(),
            essay_id=essay.id,
            student_id=essay.student_id,
            kind=kind,
            institution_id=institution_id,
            input_digest=digest,
            payload=dict(payload),
            model=model,
            prompt_ref=f"{task.value}/{kind}",
            created_at=self._clock.now(),
        )

    async def run(
        self,
        ctx: AdmissionContext,
        essay_id: UUID,
        institution_ids: list[UUID],
        *,
        refresh: bool,
        locale: str,
    ) -> EssayReviews:
        """Review the essay and each chosen university; reuse unchanged results."""
        ids = list(dict.fromkeys(institution_ids))
        if len(ids) > MAX_UNIVERSITIES:
            raise ItemLimitError(
                params={"kind": "universities", "limit": MAX_UNIVERSITIES}
            )
        await self._gate(ctx)
        uid = ctx.user_id
        async with self._uow() as uow:
            essay = await self._essay(uow, ctx, essay_id)
            count = word_count(essay.body)
            if count < REVIEW_MIN_WORDS:
                raise EssayTooShortError(
                    params={"min": REVIEW_MIN_WORDS, "count": count}
                )
            unis: list[UniContext] = []
            for iid in ids:
                uni = await load_uni_context(uow, iid)
                if uni is None:
                    raise AdmissionNotFoundError()
                unis.append(uni)
        text = essay_input(essay)
        matches = await self._closest(text)
        base_digest = await self._digest(uid, _base_key(text, locale, matches))
        async with self._uow() as uow:
            hit = (
                None
                if refresh
                else await uow.essay_reviews.find(essay.id, "base", None, base_digest)
            )
        base_cached = hit is not None
        if hit is not None:
            base = base_from(hit.payload)
        else:
            await self._hit(self._base_quota, "essay_review", uid)
            base, model = await run_base_review(
                self._ai, self._prompts, essay=text, exemplars=matches, locale=locale
            )
            async with self._uow() as uow:
                await uow.essay_reviews.save(
                    self._stored(
                        essay,
                        "base",
                        None,
                        base_digest,
                        base_payload(base),
                        model,
                        AiTask.ADMIT_ESSAY_REVIEW,
                    )
                )
                await uow.commit()
        entries: list[UniEntry] = []
        for uni in unis:
            entries.append(await self._uni(essay, text, uni, base, refresh, locale))
        return EssayReviews(base, base_cached, False, tuple(entries))

    async def _uni(
        self,
        essay: Essay,
        text: EssayInput,
        uni: UniContext,
        base: BaseReview,
        refresh: bool,
        locale: str,
    ) -> UniEntry:
        if not uni.sourced:
            return UniEntry(
                uni.institution_id, uni.name, unsourced_review(uni), False, False
            )
        uid = essay.student_id
        digest = await self._digest(uid, _uni_key(text, locale, uni))
        async with self._uow() as uow:
            hit = (
                None
                if refresh
                else await uow.essay_reviews.find(
                    essay.id, "uni", uni.institution_id, digest
                )
            )
        if hit is not None:
            return UniEntry(
                uni.institution_id, uni.name, uni_from(hit.payload), True, False
            )
        await self._hit(self._uni_quota, "essay_uni_review", uid)
        result, model = await run_uni_review(
            self._ai, self._prompts, essay=text, uni=uni, base=base, locale=locale
        )
        async with self._uow() as uow:
            await uow.essay_reviews.save(
                self._stored(
                    essay,
                    "uni",
                    uni.institution_id,
                    digest,
                    uni_payload(result),
                    model,
                    AiTask.ADMIT_ESSAY_UNI_REVIEW,
                )
            )
            await uow.commit()
        return UniEntry(uni.institution_id, uni.name, result, False, False)

    async def get(
        self, ctx: AdmissionContext, essay_id: UUID, locale: str
    ) -> EssayReviews:
        """The stored reviews, newest per university; never calls the model."""
        await self._owner(ctx)
        uid = ctx.user_id
        async with self._uow() as uow:
            essay = await self._essay(uow, ctx, essay_id)
            stored = await uow.essay_reviews.list_for_essay(essay.id)
            latest: dict[UUID, StoredReview] = {}
            for s in stored:
                if s.kind == "uni" and s.institution_id is not None:
                    latest.setdefault(s.institution_id, s)
            unis = {iid: await load_uni_context(uow, iid) for iid in latest}
        base_row = next((s for s in stored if s.kind == "base"), None)
        text = essay_input(essay)
        base: BaseReview | None = None
        base_stale = False
        if base_row is not None:
            base = base_from(base_row.payload)
            key = _base_key(text, locale, await self._closest(text))
            base_stale = await self._digest(uid, key) != base_row.input_digest
        entries: list[UniEntry] = []
        for iid, row in latest.items():
            uni = unis[iid]
            result = uni_from(row.payload)
            stale = uni is None or (
                await self._digest(uid, _uni_key(text, locale, uni)) != row.input_digest
            )
            name = uni.name if uni is not None else result.institution_name
            entries.append(UniEntry(iid, name, result, True, stale))
        return EssayReviews(base, base_row is not None, base_stale, tuple(entries))
