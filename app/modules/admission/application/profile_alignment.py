"""Alignment of the whole application against the three words."""

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.items import items_summary
from app.modules.admission.application.words import answer_texts, delimit, plain
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    ConsentRequiredError,
    QuotaExceededError,
    WordsNotSetError,
)
from app.modules.admission.domain.permissions import Permission
from app.modules.admission.domain.profile_words import ALIGNMENT, ReviewRecord
from app.modules.admission.infrastructure.ai.prompts import alignment_map as prompt
from app.modules.admission.ports.ai import PromptSource, QuotaOf, StructuredAi
from app.modules.admission.ports.consent import AI, PurposeConsents
from app.modules.admission.ports.unit_of_work import UowFactory
from app.shared.ai_tasks import AiTask
from app.shared.brand import with_brand
from app.shared.clock import Clock

SAFEGUARDING_KEY = "admission-safeguarding-support"
WEEK = dt.timedelta(days=7)


@dataclass(frozen=True, slots=True)
class AlignmentResult:
    """A stored map; `stale` when the file or the words changed since."""

    review: ReviewRecord
    stale: bool


def grade_of(levels: list[str]) -> str:
    """Return the overall letter from the three word levels (computed here)."""
    strong = levels.count("strong")
    covered = len(levels) - levels.count("none")
    if strong == len(levels):
        return "A"
    if covered == len(levels):
        return "B"
    return "C" if covered == len(levels) - 1 else "D"


def _level(carriers: list[dict[str, Any]]) -> str:
    points = sum(2 if c["strength"] == "strong" else 1 for c in carriers)
    return "strong" if points >= 2 else "weak" if points else "none"


class AlignmentService:
    """Run and read the alignment map."""

    def __init__(
        self,
        uow_factory: UowFactory,
        access: AccessPolicy,
        ai: StructuredAi,
        consents: PurposeConsents,
        clock: Clock,
        weekly_limit: QuotaOf,
        prompts: PromptSource,
    ) -> None:
        """Keep the collaborators and the reader of the soft weekly limit."""
        self._uow = uow_factory
        self._access = access
        self._ai = ai
        self._consents = consents
        self._clock = clock
        self._limit = weekly_limit
        self._prompts = prompts

    async def _input(
        self, student_id: UUID
    ) -> tuple[
        dict[str, str], dict[str, str], tuple[str, ...], int, list[dict[str, Any]]
    ]:
        """Return answer texts, course titles, the words, their version and items."""
        async with self._uow() as uow:
            profile = await uow.profiles.get(student_id)
            words = await uow.profiles.get_words(student_id)
            courses = [c for c in await uow.courses.list_for(student_id) if c.included]
            items = await uow.items.list_for(student_id)
            metrics = await uow.items.metrics_for([i.id for i in items])
        if words is None or len(words.words) == 0:
            raise WordsNotSetError()
        titles = {str(c.id): c.title for c in courses if c.id is not None}
        return (
            answer_texts(profile.answers) if profile else {},
            titles,
            words.words,
            words.version,
            items_summary(items, metrics),
        )

    @staticmethod
    def _hash(
        texts: dict[str, str],
        titles: dict[str, str],
        words: tuple[str, ...],
        v: int,
        items: list[dict[str, Any]],
    ) -> str:
        doc = json.dumps(
            [prompt.PROMPT_VERSION, prompt.SCHEMA_VERSION, v, words, texts, titles]
            + [items],
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(doc.encode()).hexdigest()

    async def run(self, ctx: AdmissionContext) -> AlignmentResult:
        """Return the cached map of this exact input, or compute a new one."""
        res = await self._access.resolve(ctx, ctx.user_id)
        if not res.owner:
            raise AdmissionForbiddenError(params={"permission": "alignment:run"})
        texts, titles, words, version, items = await self._input(ctx.user_id)
        digest = self._hash(texts, titles, words, version, items)
        async with self._uow() as uow:
            cached = await uow.reviews.find(ALIGNMENT, ctx.user_id, digest)
        if cached is not None:
            return AlignmentResult(cached, False)
        granted = (await self._consents.granted([ctx.user_id])).get(
            ctx.user_id, frozenset()
        )
        if AI not in granted:
            raise ConsentRequiredError(params={"purpose": AI})
        now = self._clock.now()
        async with self._uow() as uow:
            used = await uow.reviews.count_since(
                ctx.user_id, AiTask.ADMIT_ALIGNMENT_MAP.value, now - WEEK
            )
        limit = await self._limit(ctx.user_id)
        if limit is not None and used >= limit:
            raise QuotaExceededError(
                params={
                    "task": AiTask.ADMIT_ALIGNMENT_MAP.value,
                    "limit": limit,
                    "period": "week",
                }
            )
        lines = [f"Words: {', '.join(words)}"]
        lines += [f"[answer:{k}] {v}" for k, v in texts.items()]
        lines += [f"[course:{k}] {v}" for k, v in titles.items()]
        lines += [
            f"[item:{i['id']}] {json.dumps(i, ensure_ascii=False)}" for i in items
        ]
        data, model = await self._ai.json(
            task=AiTask.ADMIT_ALIGNMENT_MAP,
            system=with_brand(
                await self._prompts.text(AiTask.ADMIT_ALIGNMENT_MAP, "system", "")
            ),
            user=delimit(lines),
            schema_name=prompt.SCHEMA_NAME,
            schema=prompt.SCHEMA,
            max_tokens=2500,
        )
        review = self._review(
            ctx.user_id,
            digest,
            version,
            words,
            (set(texts), set(titles), {i["id"] for i in items}),
            data,
            model,
        )
        async with self._uow() as uow:
            stored = await uow.reviews.add(review)
            await uow.commit()
        return AlignmentResult(stored, False)

    @staticmethod
    def _review(
        student_id: UUID,
        digest: str,
        version: int,
        words: tuple[str, ...],
        known_ids: tuple[set[str], set[str], set[str]],
        data: dict[str, Any],
        model: str,
    ) -> ReviewRecord:
        """Validate the model's map and compute levels and the overall letter."""
        base: dict[str, Any] = {
            "student_id": student_id,
            "target_kind": ALIGNMENT,
            "target_id": student_id,
            "input_hash": digest,
            "task": AiTask.ADMIT_ALIGNMENT_MAP.value,
            "prompt_version": prompt.PROMPT_VERSION,
            "schema_version": prompt.SCHEMA_VERSION,
            "rubric_version": prompt.RUBRIC_VERSION,
            "model": model,
            "words_version": version,
        }
        if data.get("safeguarding_concern") is True:
            return ReviewRecord(
                **base,
                safety_flag="safeguarding",
                payload={"message_key": SAFEGUARDING_KEY},
            )
        known = dict(zip(("answer", "course", "item"), known_ids, strict=True))

        def valid(kind: Any, ref: Any) -> bool:
            return str(ref) in known.get(str(kind), set())

        by_word = {str(w.get("word", "")).casefold(): w for w in data.get("words", [])}
        fits: list[dict[str, Any]] = []
        for word in words:
            raw = by_word.get(word.casefold(), {})
            carriers = [
                {
                    "ref_kind": c["ref_kind"],
                    "ref_id": str(c["ref_id"]),
                    "strength": c["strength"],
                }
                for c in raw.get("carriers", [])
                if valid(c.get("ref_kind"), c.get("ref_id"))
                and c.get("strength") in {"weak", "strong"}
            ]
            fits.append({"word": word, "level": _level(carriers), "carriers": carriers})
        carried = {(c["ref_kind"], c["ref_id"]) for f in fits for c in f["carriers"]}
        orphans = [
            {"ref_kind": o["ref_kind"], "ref_id": str(o["ref_id"])}
            for o in data.get("orphans", [])
            if valid(o.get("ref_kind"), o.get("ref_id"))
            and (o["ref_kind"], str(o["ref_id"])) not in carried
        ]
        gaps = [
            {"word": g["word"], "advice": plain(str(g.get("advice", "")))[:300]}
            for g in data.get("gaps", [])
            if str(g.get("word", "")).casefold() in {w.casefold() for w in words}
        ]
        levels = [f["level"] for f in fits]
        return ReviewRecord(
            **base,
            grades={f["word"]: f["level"] for f in fits},
            overall=grade_of(levels),
            payload={"words": fits, "orphans": orphans, "gaps": gaps},
        )

    async def latest(
        self, ctx: AdmissionContext, student_id: UUID
    ) -> AlignmentResult | None:
        """Return the newest map and whether the file changed since."""
        res = await self._access.require(
            ctx, student_id, Permission.WORDS_READ, object_type="alignment"
        )
        async with self._uow() as uow:
            review = await uow.reviews.latest(student_id, ALIGNMENT)
        if review is None:
            if res.owner:
                return None
            raise AdmissionNotFoundError()
        try:
            digest = self._hash(*await self._input(student_id))
        except WordsNotSetError:
            return AlignmentResult(review, True)
        return AlignmentResult(review, digest != review.input_hash)
