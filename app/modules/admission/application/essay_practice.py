"""Daily creative practice: one theme a day, a free text, an optional AI evaluation.

The theme is the same for every student and changes at local midnight. The text
is stored sealed; the evaluation is cached with it, so a repeat costs no model
call and no quota until the text changes. The coach daily limit applies.
"""

import datetime as dt
from dataclasses import dataclass
from typing import Any, Final

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.essay_prompts import FlowGate
from app.modules.admission.application.words import delimit
from app.modules.admission.domain.errors import EssayTooShortError
from app.modules.admission.domain.essay_flow import (
    PRACTICE_HISTORY,
    PRACTICE_KEYS,
    PRACTICE_MAX,
    PRACTICE_MIN_WORDS,
    PRACTICE_THEMES,
    PracticeEntry,
    PracticeEvaluation,
    PracticeScore,
    theme_for,
)
from app.modules.admission.domain.essays import word_count
from app.modules.admission.infrastructure.ai.prompts import essay_flow as prompt
from app.modules.admission.ports.ai import PromptSource, QuotaOf, StructuredAi
from app.modules.admission.ports.consent import AI
from app.modules.admission.ports.unit_of_work import UowFactory
from app.shared.ai_tasks import AiTask
from app.shared.brand import with_brand
from app.shared.clock import Clock, local_today
from app.shared.ids import new_id
from app.shared.rate_limit import RateLimiter

_DAY: Final = 86400
_TOKENS: Final = 1200


@dataclass(frozen=True, slots=True)
class PracticeToday:
    """Today's theme and the student's entry for it, if any."""

    day: dt.date
    theme: str
    prompt: str
    entry: PracticeEntry | None


def _line(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _lines(values: Any, limit: int) -> tuple[str, ...]:
    out = (_line(v, prompt.LINE_MAX) for v in (values or [])[:limit])
    return tuple(v for v in out if v)


def _score(value: Any) -> int:
    try:
        return min(max(int(value), 0), 5)
    except (TypeError, ValueError):
        return 0


def evaluation_from(data: dict[str, Any]) -> PracticeEvaluation:
    """Turn the model's reply into the four ordered scores and short lists."""
    given: dict[str, Any] = {}
    for raw in data.get("scores") or []:
        if isinstance(raw, dict) and raw.get("key") in PRACTICE_KEYS:
            given.setdefault(raw["key"], raw)
    scores = tuple(
        PracticeScore(
            key,
            _score(given.get(key, {}).get("score")),
            _line(given.get(key, {}).get("comment"), prompt.LINE_MAX),
        )
        for key in PRACTICE_KEYS
    )
    return PracticeEvaluation(
        summary=_line(data.get("summary"), prompt.SUMMARY_MAX),
        scores=scores,
        praise=_lines(data.get("praise"), prompt.MAX_POINTS),
        try_next=_lines(data.get("try_next"), prompt.MAX_POINTS),
        idea_seeds=_lines(data.get("idea_seeds"), prompt.MAX_POINTS),
    )


class EssayPracticeService:
    """Today's theme, the student's entry, its evaluation and the history."""

    def __init__(
        self,
        uow_factory: UowFactory,
        gate: FlowGate,
        ai: StructuredAi,
        clock: Clock,
        limiter: RateLimiter,
        daily_limit: QuotaOf,
        prompts: PromptSource,
    ) -> None:
        """Keep the collaborators and the reader of the soft daily coach limit."""
        self._uow = uow_factory
        self._gate = gate
        self._ai = ai
        self._clock = clock
        self._limiter = limiter
        self._limit = daily_limit
        self._prompts = prompts

    async def today(self, ctx: AdmissionContext) -> PracticeToday:
        """The theme of the local day and my entry for it."""
        await self._gate.owner(ctx)
        day = local_today(self._clock)
        async with self._uow() as uow:
            entry = await uow.practice.get(ctx.user_id, day)
        return self._view(day, entry)

    async def save(self, ctx: AdmissionContext, body: str) -> PracticeToday:
        """Write today's entry; a changed text drops the stale evaluation."""
        await self._gate.owner(ctx)
        body = body[:PRACTICE_MAX]
        day = local_today(self._clock)
        theme = theme_for(day)
        now = self._clock.now()
        async with self._uow() as uow:
            old = await uow.practice.get(ctx.user_id, day)
            if old is not None and old.body == body:
                return self._view(day, old)
            entry = await uow.practice.save(
                PracticeEntry(
                    id=old.id if old else new_id(),
                    student_id=ctx.user_id,
                    day=day,
                    theme=theme,
                    body=body,
                    created_at=old.created_at if old else now,
                    updated_at=now,
                )
            )
            await uow.commit()
        return self._view(day, entry)

    async def evaluate(self, ctx: AdmissionContext, locale: str) -> PracticeToday:
        """Evaluate today's entry (AI consent, daily limit); cached until it changes."""
        await self._gate.require(ctx, AI)
        day = local_today(self._clock)
        async with self._uow() as uow:
            entry = await uow.practice.get(ctx.user_id, day)
        count = word_count(entry.body) if entry else 0
        if entry is None or count < PRACTICE_MIN_WORDS:
            raise EssayTooShortError(params={"min": PRACTICE_MIN_WORDS, "count": count})
        if entry.evaluation is not None:
            return self._view(day, entry)
        limit = await self._limit(ctx.user_id)
        if limit is not None:
            await self._limiter.hit(
                f"admission:essay_coach:{ctx.user_id}",
                limit=limit,
                window_seconds=_DAY,
            )
        schema_name, schema = prompt.SCHEMAS["practice"]
        data, model = await self._ai.json(
            task=AiTask.ADMIT_ESSAY_PRACTICE,
            system=with_brand(
                await self._prompts.text(
                    AiTask.ADMIT_ESSAY_PRACTICE, "practice", locale
                )
            ),
            user=delimit(
                [
                    f"Language: {locale}",
                    f"Theme: {PRACTICE_THEMES.get(entry.theme, entry.theme)}",
                    f"Entry:\n{entry.body}",
                ]
            ),
            schema_name=schema_name,
            schema=schema,
            max_tokens=_TOKENS,
        )
        entry.evaluation = evaluation_from(data)
        entry.model = model
        async with self._uow() as uow:
            current = await uow.practice.get(ctx.user_id, day)
            if current is not None and current.body != entry.body:
                return self._view(day, current)  # edited meanwhile: keep it unscored
            saved = await uow.practice.save(entry)
            await uow.commit()
        return self._view(day, saved)

    async def history(self, ctx: AdmissionContext) -> list[PracticeEntry]:
        """My recent entries, newest first."""
        await self._gate.owner(ctx)
        async with self._uow() as uow:
            return await uow.practice.recent(ctx.user_id, PRACTICE_HISTORY)

    @staticmethod
    def _view(day: dt.date, entry: PracticeEntry | None) -> PracticeToday:
        theme = theme_for(day)
        return PracticeToday(day, theme, PRACTICE_THEMES[theme], entry)
