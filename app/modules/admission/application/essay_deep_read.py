"""Deep read of an essay, and the group critique over its target universities.

The deep read goes paragraph by paragraph: what each reveals, how unique the
essay is, which moments land, and the one fix that matters most. It is stored
as a review of kind `deep` under a keyed digest of its input, so an unchanged
essay is served without a model call. The group critique runs the existing
review service once per target university of the essay.
"""

import datetime as dt
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any, Final, Literal
from uuid import UUID

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.essay_prompts import FlowGate
from app.modules.admission.application.essay_review_core import (
    DegenerateReviewError,
    essay_input,
    input_key,
)
from app.modules.admission.application.essay_reviews import (
    EssayReviews,
    EssayReviewService,
)
from app.modules.admission.application.review_checks import nfc
from app.modules.admission.application.words import delimit, plain
from app.modules.admission.domain.errors import (
    AdmissionNotFoundError,
    EssayTooShortError,
)
from app.modules.admission.domain.essay_flow import DeepRead, Moment, ParagraphRead
from app.modules.admission.domain.essay_reviews import REVIEW_MIN_WORDS, EssayInput
from app.modules.admission.domain.essay_text import paragraphs as essay_paragraphs
from app.modules.admission.domain.essays import Essay, word_count
from app.modules.admission.infrastructure.ai.prompts import essay_flow as flow
from app.modules.admission.infrastructure.ai.prompts.essay_review import DIMENSIONS
from app.modules.admission.ports.ai import PromptSource, QuotaOf, StructuredAi
from app.modules.admission.ports.consent import AI
from app.modules.admission.ports.essay_crypto import EssayCipher
from app.modules.admission.ports.unit_of_work import AdmissionUnitOfWork, UowFactory
from app.shared.ai_tasks import AiTask
from app.shared.brand import with_brand
from app.shared.clock import Clock
from app.shared.ids import new_id
from app.shared.rate_limit import RateLimiter

from app.modules.admission.domain.essay_reviews import StoredReview  # isort: skip

_WEEK: Final = 7 * 86400
_PURPOSE: Final = "essay_deep_read"
_TOKENS: Final = 3000
_BODY_TO_MODEL: Final = 12000
_ROLES: Final = ("hook", "context", "turn", "evidence", "insight", "close")
_STRENGTHS: Final = ("strong", "ok", "weak")
_KINDS: Final = ("surprising", "fresh", "earned")


@dataclass(frozen=True, slots=True)
class DeepReadResult:
    """A stored deep read; `stale` when the essay changed since it was made."""

    read: DeepRead
    cached: bool
    stale: bool


@dataclass(frozen=True, slots=True)
class ReadHistoryItem:
    """One past deep read of an essay, with the universities reviewed after it."""

    id: UUID
    created_at: dt.datetime
    words: int
    summary: str
    universities: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class StoredRead:
    """One past deep read; `latest` when no newer read exists."""

    id: UUID
    created_at: dt.datetime
    read: DeepRead
    latest: bool


@dataclass(frozen=True, slots=True)
class ReadState:
    """What the ledger shows of an essay's deep read."""

    state: Literal["none", "fresh", "stale"]
    uniqueness: int | None
    read_at: dt.datetime | None


def _flat(text: str) -> str:
    return " ".join(nfc(text).split())


def _line(value: Any, limit: int) -> str:
    return nfc(plain(str(value or ""))).strip()[:limit]


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def paragraphs_of(body: str) -> list[str]:
    """The paragraphs of an essay: scene breaks are transitions, not paragraphs."""
    return essay_paragraphs(body)


def _read(data: dict[str, Any], body: str) -> DeepRead:
    """Turn the model's reply into a reading the code can stand behind."""
    count = max(len(paragraphs_of(body)), 1)
    haystack = _flat(body)
    seen: dict[int, ParagraphRead] = {}
    for raw in data.get("paragraphs") or []:
        n = _int(raw.get("paragraph"))
        if 1 <= n <= count and n not in seen:
            role = raw.get("role")
            strength = raw.get("strength")
            seen[n] = ParagraphRead(
                n,
                role if role in _ROLES else "context",
                _line(raw.get("reveals"), flow.LINE_MAX),
                strength if strength in _STRENGTHS else "ok",
            )
    moments: list[Moment] = []
    for raw in data.get("moments") or []:
        quote = _flat(str(raw.get("quote") or ""))[: flow.QUOTE_MAX]
        n = _int(raw.get("paragraph"))
        if quote and quote in haystack and 1 <= n <= count:
            kind = raw.get("kind")
            moments.append(Moment(n, quote, kind if kind in _KINDS else "fresh"))
    dim = data.get("fix_dimension")
    tropes = [_line(t, 80) for t in data.get("tropes") or []]
    return DeepRead(
        paragraphs=tuple(seen[n] for n in sorted(seen)),
        uniqueness=min(max(_int(data.get("uniqueness")), 0), 100),
        uniqueness_note=_line(data.get("uniqueness_note"), flow.SUMMARY_MAX),
        tropes=tuple(t for t in tropes if t)[: flow.MAX_TROPES],
        moments=tuple(moments[: flow.MAX_MOMENTS]),
        fix_paragraph=min(max(_int(data.get("fix_paragraph"), 1), 1), count),
        fix_dimension=dim if dim in DIMENSIONS else DIMENSIONS[0],
        fix_problem=_line(data.get("fix_problem"), flow.LINE_MAX),
        fix_try=_line(data.get("fix_try"), flow.LINE_MAX),
    )


def deep_from(payload: dict[str, Any]) -> DeepRead:
    """Rebuild a reading from its stored payload."""
    return DeepRead(
        paragraphs=tuple(ParagraphRead(**p) for p in payload["paragraphs"]),
        uniqueness=payload["uniqueness"],
        uniqueness_note=payload["uniqueness_note"],
        tropes=tuple(payload["tropes"]),
        moments=tuple(Moment(**m) for m in payload["moments"]),
        fix_paragraph=payload["fix_paragraph"],
        fix_dimension=payload["fix_dimension"],
        fix_problem=payload["fix_problem"],
        fix_try=payload["fix_try"],
    )


def _key(text: EssayInput, locale: str) -> str:
    return input_key(
        "deep",
        locale,
        text.kind,
        text.title,
        text.prompt_text,
        str(text.word_limit),
        text.body,
        flow.DEEP_READ,
    )


class EssayDeepReadService:
    """Deep read of one essay, and the group critique over its targets."""

    def __init__(
        self,
        uow_factory: UowFactory,
        gate: FlowGate,
        ai: StructuredAi,
        clock: Clock,
        limiter: RateLimiter,
        quota: QuotaOf,
        prompts: PromptSource,
        cipher: EssayCipher,
        reviews: EssayReviewService,
    ) -> None:
        """Keep the collaborators and the reader of the weekly review limit."""
        self._uow = uow_factory
        self._gate = gate
        self._ai = ai
        self._clock = clock
        self._limiter = limiter
        self._quota = quota
        self._prompts = prompts
        self._cipher = cipher
        self._reviews = reviews

    @staticmethod
    async def _essay(
        uow: AdmissionUnitOfWork, ctx: AdmissionContext, eid: UUID
    ) -> Essay:
        essay = await uow.essays.get(eid)
        if essay is None or essay.student_id != ctx.user_id:
            raise AdmissionNotFoundError()
        return essay

    async def _digest(self, uid: UUID, text: EssayInput, locale: str) -> str:
        return await self._cipher.digest(uid, _PURPOSE, _key(text, locale))

    async def run(
        self, ctx: AdmissionContext, essay_id: UUID, *, refresh: bool, locale: str
    ) -> DeepReadResult:
        """Read the essay closely; an unchanged essay is served from the store."""
        await self._gate.require(ctx, AI)
        uid = ctx.user_id
        async with self._uow() as uow:
            essay = await self._essay(uow, ctx, essay_id)
        count = word_count(essay.body)
        if count < REVIEW_MIN_WORDS:
            raise EssayTooShortError(params={"min": REVIEW_MIN_WORDS, "count": count})
        text = essay_input(essay)
        digest = await self._digest(uid, text, locale)
        if not refresh:
            async with self._uow() as uow:
                hit = await uow.essay_reviews.find(essay.id, "deep", None, digest)
            if hit is not None:
                return DeepReadResult(deep_from(hit.payload), True, False)
        limit = await self._quota(uid)
        if limit is not None:
            await self._limiter.hit(
                f"admission:essay_review:{uid}", limit=limit, window_seconds=_WEEK
            )
        body = text.body[:_BODY_TO_MODEL]
        numbered = [f"[{i}] {p}" for i, p in enumerate(paragraphs_of(body), start=1)]
        lines = [f"Language: {locale}", f"Essay kind: {text.kind}"]
        if text.prompt_text:
            lines.append(f"Prompt: {text.prompt_text}")
        lines.append(f"Word count: {count}")
        lines.append("Essay:")
        lines.extend(numbered)
        task = AiTask.ADMIT_ESSAY_DEEP_READ
        schema = flow.SCHEMAS["deep_read"]
        data, model = await self._ai.json(
            task=task,
            system=with_brand(await self._prompts.text(task, "deep_read", locale)),
            user=delimit(lines),
            schema_name=schema[0],
            schema=schema[1],
            max_tokens=_TOKENS,
        )
        read = _read(data, body)
        if not read.paragraphs:
            raise DegenerateReviewError()
        async with self._uow() as uow:
            await uow.essay_reviews.save(
                StoredReview(
                    id=new_id(),
                    essay_id=essay.id,
                    student_id=uid,
                    kind="deep",
                    institution_id=None,
                    input_digest=digest,
                    payload={**asdict(read), "words": count},
                    model=model,
                    prompt_ref=f"{task.value}/deep",
                    created_at=self._clock.now(),
                )
            )
            await uow.commit()
        return DeepReadResult(read, False, False)

    async def get(
        self, ctx: AdmissionContext, essay_id: UUID, locale: str
    ) -> DeepReadResult | None:
        """The stored deep read, newest first; None when there is none."""
        await self._gate.owner(ctx)
        async with self._uow() as uow:
            essay = await self._essay(uow, ctx, essay_id)
            stored = await uow.essay_reviews.list_for_essay(essay.id)
        row = next((s for s in stored if s.kind == "deep"), None)
        if row is None:
            return None
        digest = await self._digest(ctx.user_id, essay_input(essay), locale)
        return DeepReadResult(deep_from(row.payload), True, digest != row.input_digest)

    async def history(
        self, ctx: AdmissionContext, essay_id: UUID
    ) -> list[ReadHistoryItem]:
        """Every stored deep read of my essay, newest first; no model call."""
        await self._gate.owner(ctx)
        async with self._uow() as uow:
            essay = await self._essay(uow, ctx, essay_id)
            stored = await uow.essay_reviews.list_for_essay(essay.id)
        reads = sorted(
            (s for s in stored if s.kind == "deep"),
            key=lambda s: s.created_at,
            reverse=True,
        )
        unis = [s for s in stored if s.kind == "uni" and s.institution_id]
        out: list[ReadHistoryItem] = []
        upper: dt.datetime | None = None
        for r in reads:
            ids = [
                u.institution_id
                for u in unis
                if u.institution_id is not None
                and u.created_at >= r.created_at
                and (upper is None or u.created_at < upper)
            ]
            note = _line(r.payload.get("uniqueness_note"), flow.SUMMARY_MAX)
            out.append(
                ReadHistoryItem(
                    r.id,
                    r.created_at,
                    _int(r.payload.get("words")),
                    note,
                    tuple(dict.fromkeys(ids)),
                )
            )
            upper = r.created_at
        return out

    async def stored_read(
        self, ctx: AdmissionContext, essay_id: UUID, read_id: UUID
    ) -> StoredRead:
        """One past deep read of my essay by id."""
        await self._gate.owner(ctx)
        async with self._uow() as uow:
            essay = await self._essay(uow, ctx, essay_id)
            stored = await uow.essay_reviews.list_for_essay(essay.id)
        reads = sorted(
            (s for s in stored if s.kind == "deep"),
            key=lambda s: s.created_at,
            reverse=True,
        )
        row = next((s for s in reads if s.id == read_id), None)
        if row is None:
            raise AdmissionNotFoundError()
        return StoredRead(
            row.id, row.created_at, deep_from(row.payload), row is reads[0]
        )

    async def states(
        self, ctx: AdmissionContext, essays: Sequence[Essay], locale: str
    ) -> dict[UUID, ReadState]:
        """The stored deep read of each of my essays: score and freshness, no model."""
        await self._gate.owner(ctx)
        out: dict[UUID, ReadState] = {}
        async with self._uow() as uow:
            for essay in essays:
                if essay.student_id != ctx.user_id or essay.unreadable:
                    continue
                stored = await uow.essay_reviews.list_for_essay(essay.id)
                row = next((s for s in stored if s.kind == "deep"), None)
                if row is None:
                    out[essay.id] = ReadState("none", None, None)
                    continue
                digest = await self._digest(ctx.user_id, essay_input(essay), locale)
                out[essay.id] = ReadState(
                    "fresh" if digest == row.input_digest else "stale",
                    _int(row.payload.get("uniqueness")),
                    row.created_at,
                )
        return out

    async def group_critique(
        self,
        ctx: AdmissionContext,
        essay_id: UUID,
        *,
        refresh: bool,
        locale: str,
        institution_ids: Sequence[UUID] | None = None,
    ) -> EssayReviews:
        """Review the essay for every university it targets, under that prompt."""
        await self._gate.owner(ctx)
        async with self._uow() as uow:
            essay = await self._essay(uow, ctx, essay_id)
        ids = [t.institution_id for t in essay.targets if t.institution_id is not None]
        if institution_ids is not None:
            chosen = set(institution_ids)
            ids = [i for i in ids if i in chosen]
        return await self._reviews.run(
            ctx, essay_id, list(dict.fromkeys(ids)), refresh=refresh, locale=locale
        )
