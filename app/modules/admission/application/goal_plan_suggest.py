"""AI proposals of goal-plan milestones; nothing is stored until the student saves."""

import datetime as dt
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.items import items_summary
from app.modules.admission.application.review_checks import nfc
from app.modules.admission.application.student_context import student_block
from app.modules.admission.application.words import delimit, plain
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    ConsentRequiredError,
    WordsNotSetError,
)
from app.modules.admission.domain.goal_plan import TITLE_MAX
from app.modules.admission.infrastructure.ai.prompts import goal_plan as prompt
from app.modules.admission.ports.ai import PromptSource, QuotaOf, StructuredAi
from app.modules.admission.ports.consent import AI, PurposeConsents
from app.modules.admission.ports.student_search import StudentDataSearch
from app.modules.admission.ports.unit_of_work import UowFactory
from app.shared.ai_tasks import AiTask
from app.shared.brand import with_brand
from app.shared.clock import Clock
from app.shared.rate_limit import RateLimiter

_WEEK: Final = 7 * 24 * 3600
_TOKENS: Final = 1200


@dataclass(frozen=True, slots=True)
class Suggestion:
    """A proposed milestone, not yet saved."""

    title: str
    item_id: UUID | None
    due_month: dt.date


def _add_months(day: dt.date, months: int) -> dt.date:
    index = day.year * 12 + day.month - 1 + months
    return dt.date(index // 12, index % 12 + 1, 1)


class GoalPlanSuggester:
    """Ask the model for next steps; the owner needs AI consent and a quota."""

    def __init__(
        self,
        uow_factory: UowFactory,
        access: AccessPolicy,
        ai: StructuredAi,
        consents: PurposeConsents,
        clock: Clock,
        limiter: RateLimiter,
        weekly_limit: QuotaOf,
        prompts: PromptSource,
        search: StudentDataSearch | None = None,
    ) -> None:
        """Keep the collaborators and the reader of the soft weekly limit."""
        self._uow = uow_factory
        self._access = access
        self._ai = ai
        self._consents = consents
        self._clock = clock
        self._limiter = limiter
        self._limit = weekly_limit
        self._prompts = prompts
        self._search = search

    async def suggest(self, ctx: AdmissionContext, locale: str) -> list[Suggestion]:
        """Return up to six proposals that fit the room left in the plan."""
        res = await self._access.resolve(ctx, ctx.user_id)
        if not res.owner:
            raise AdmissionForbiddenError(params={"permission": "activities:edit"})
        granted = (await self._consents.granted([ctx.user_id])).get(
            ctx.user_id, frozenset()
        )
        if AI not in granted:
            raise ConsentRequiredError(params={"purpose": AI})
        async with self._uow() as uow:
            words = await uow.items.words(ctx.user_id)
            items = await uow.items.list_for(ctx.user_id)
            metrics = await uow.items.metrics_for([i.id for i in items])
            planned = await uow.goals.list_for(ctx.user_id)
        if words is None or not words.words:
            raise WordsNotSetError()
        limit = await self._limit(ctx.user_id)
        if limit is not None:
            await self._limiter.hit(
                f"admission:goal_plan:{ctx.user_id}", limit=limit, window_seconds=_WEEK
            )
        summary = items_summary(items, metrics)
        lines = [f"Words: {', '.join(words.words)}", f"Language: {locale}"]
        lines += [f"[item:{i['id']}] {i}" for i in summary]
        lines += [f"[planned] {m.title}" for m in planned]
        lines += await student_block(
            self._search,
            ctx.user_id,
            list(words.words[:3]),
            ("item", "task", "test_score", "course", "grade", "profile"),
        )
        data, _ = await self._ai.json(
            task=AiTask.ADMIT_GOAL_PLAN,
            system=with_brand(
                await self._prompts.text(AiTask.ADMIT_GOAL_PLAN, "system", locale)
            ),
            user=delimit(lines),
            schema_name=prompt.SCHEMA_NAME,
            schema=prompt.SCHEMA,
            max_tokens=_TOKENS,
        )
        room = max(0, 12 - len(planned))
        known = {i["id"] for i in summary}
        return self._clean(data, known, self._clock.now().date())[:room]

    @staticmethod
    def _clean(
        data: dict[str, Any], known: set[str], today: dt.date
    ) -> list[Suggestion]:
        """Keep valid, distinct, plain proposals; drop unknown item ids."""
        seen: set[str] = set()
        out: list[Suggestion] = []
        for raw in data.get("suggestions", [])[: prompt.MAX_SUGGESTED]:
            title = nfc(plain(str(raw.get("title", "")))).strip()[:TITLE_MAX]
            if not title or title.casefold() in seen:
                continue
            seen.add(title.casefold())
            ref = str(raw.get("item_id", "")).strip()
            try:
                months = int(raw.get("months_ahead", 1))
            except (TypeError, ValueError):
                months = 1
            months = min(max(months, 1), prompt.MAX_MONTHS_AHEAD)
            out.append(
                Suggestion(
                    title,
                    UUID(ref) if ref in known else None,
                    _add_months(today.replace(day=1), months),
                )
            )
        return out
