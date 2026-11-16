"""AI task suggestions: drafts for the owner to review and accept."""

import datetime as dt
from typing import Any, Final
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.review_checks import nfc
from app.modules.admission.application.student_context import student_block
from app.modules.admission.application.words import delimit, plain
from app.modules.admission.domain.calendar import TASHKENT
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    CharLimitError,
    ConsentRequiredError,
    InvalidAnswerError,
)
from app.modules.admission.domain.tasks import (
    PRIORITIES,
    SUGGEST_MAX,
    Task,
    TaskLink,
    TaskStep,
    clean_link,
)
from app.modules.admission.infrastructure.ai.prompts import tasks_suggest as prompt
from app.modules.admission.ports.ai import PromptSource, QuotaOf, StructuredAi
from app.modules.admission.ports.consent import AI, PurposeConsents
from app.modules.admission.ports.student_search import StudentDataSearch
from app.modules.admission.ports.unit_of_work import UowFactory
from app.shared.ai_tasks import AiTask
from app.shared.brand import with_brand
from app.shared.clock import Clock
from app.shared.ids import new_id
from app.shared.rate_limit import RateLimiter

_WEEK: Final = 7 * 24 * 3600
_TOKENS: Final = 2500
_BAD = (InvalidAnswerError, CharLimitError)


def _text(value: Any) -> str:
    return nfc(plain(value)) if isinstance(value, str) else ""


def _link(label: Any, url: Any, kind: Any) -> TaskLink | None:
    link = TaskLink(
        _text(label), _text(url), "internal" if kind == "internal" else "external"
    )
    return link if link.label and link.url else None


def _valid_link(link: TaskLink | None) -> TaskLink | None:
    """The link when it passes the domain checks, else None."""
    if link is None:
        return None
    try:
        return clean_link(link)
    except _BAD:
        return None


def _date(value: Any, today: dt.date) -> dt.date | None:
    try:
        day = dt.date.fromisoformat(str(value).strip())
    except ValueError:
        return None
    return day if day >= today else None


def clean_suggestions(
    data: dict[str, Any], student_id: UUID, today: dt.date, taken: set[str]
) -> list[Task]:
    """Valid drafts (source `ai`) of the model's document; bad parts are dropped."""
    raw = data.get("tasks")
    out: list[Task] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict) or len(out) >= SUGGEST_MAX:
            continue
        priority = item.get("priority")
        steps = []
        for s in item.get("steps") or []:
            if not isinstance(s, dict) or not _text(s.get("title")):
                continue
            link = _valid_link(
                _link(s.get("link_label"), s.get("link_url"), s.get("link_kind"))
            )
            steps.append(TaskStep(new_id(), _text(s["title"]), False, link))
        links = [
            x
            for x in (
                _valid_link(_link(k.get("label"), k.get("url"), k.get("kind")))
                for k in item.get("links") or []
                if isinstance(k, dict)
            )
            if x is not None
        ]
        task = Task(
            id=new_id(),
            student_id=student_id,
            title=_text(item.get("title")),
            description=_text(item.get("description")),
            priority=priority if priority in PRIORITIES else "medium",
            deadline=_date(item.get("deadline"), today),
            created_by="ai",
            steps=tuple(steps),
            links=tuple(links),
        )
        key = task.title.casefold()
        if key in taken:
            continue
        try:
            task.validate()
        except _BAD:
            continue
        taken.add(key)
        out.append(task)
    return out


class TaskSuggester:
    """Ask the model for tasks; the owner needs AI consent and a weekly quota."""

    def __init__(
        self,
        uow_factory: UowFactory,
        access: AccessPolicy,
        ai: StructuredAi,
        consents: PurposeConsents,
        limiter: RateLimiter,
        weekly_limit: QuotaOf,
        prompts: PromptSource,
        clock: Clock,
        search: StudentDataSearch | None = None,
    ) -> None:
        """Keep the collaborators and the reader of the soft weekly limit."""
        self._uow = uow_factory
        self._access = access
        self._ai = ai
        self._consents = consents
        self._limiter = limiter
        self._limit = weekly_limit
        self._prompts = prompts
        self._clock = clock
        self._search = search

    async def _guard(self, ctx: AdmissionContext) -> None:
        res = await self._access.resolve(ctx, ctx.user_id)
        if not res.owner:
            raise AdmissionForbiddenError(params={"permission": "deadlines:manage"})
        granted = (await self._consents.granted([ctx.user_id])).get(
            ctx.user_id, frozenset()
        )
        if AI not in granted:
            raise ConsentRequiredError(params={"purpose": AI})

    async def _lines(self, student_id: UUID, locale: str, today: dt.date) -> list[str]:
        lines = [f"Language: {locale}", f"Today: {today.isoformat()}"]
        async with self._uow() as uow:
            profile = await uow.profiles.get(student_id)
            if profile is not None:
                lines.append(f"[stage] {profile.stage}")
                lines += [f"[profile:{k}] {v}" for k, v in profile.answers.items() if v]
            for entry in await uow.shortlist.entries(student_id):
                inst = await uow.catalog.institution(entry.institution_id)
                name = inst.name if inst else str(entry.institution_id)
                lines.append(f"[university] {name}, round {entry.round}")
                for d in await uow.deadlines.current(
                    institution_id=entry.institution_id
                ):
                    if d.local_date is not None and d.round == entry.round:
                        lines.append(f"[deadline] {name}: {d.local_date.isoformat()}")
            for essay in await uow.essays.list_for(student_id):
                lines.append(
                    f"[essay] {essay.title or essay.kind}, {essay.kind}, "
                    f"{essay.status}, {len(essay.body.split())} words"
                )
            for task in await uow.tasks.list_for(student_id):
                if task.status != "done":
                    lines.append(f"[open task] {task.title}")
        lines += await student_block(
            self._search,
            student_id,
            ["deadline", "essay", "test score", "application"],
            ("item", "task", "test_score", "course", "grade", "profile"),
        )
        return lines

    async def suggest(self, ctx: AdmissionContext, locale: str) -> list[Task]:
        """Return unsaved drafts; the owner accepts the ones they want."""
        await self._guard(ctx)
        today = self._clock.now().astimezone(TASHKENT).date()
        lines = await self._lines(ctx.user_id, locale, today)
        limit = await self._limit(ctx.user_id)
        if limit is not None:
            await self._limiter.hit(
                f"admission:tasks:{ctx.user_id}", limit=limit, window_seconds=_WEEK
            )
        data, _ = await self._ai.json(
            task=AiTask.ADMIT_TASKS_SUGGEST,
            system=with_brand(
                await self._prompts.text(AiTask.ADMIT_TASKS_SUGGEST, "system", locale)
            ),
            user=delimit(lines),
            schema_name=prompt.SCHEMA_NAME,
            schema=prompt.SCHEMA,
            max_tokens=_TOKENS,
        )
        mark = "[open task] "
        taken = {x[len(mark) :].casefold() for x in lines if x.startswith(mark)}
        return clean_suggestions(
            data if isinstance(data, dict) else {}, ctx.user_id, today, taken
        )
