"""Project ideas for a student: two web searches, one model call, a kept history."""

import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.review_checks import nfc
from app.modules.admission.application.study_focus import load_study_focus
from app.modules.admission.application.words import delimit, plain
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    ConsentRequiredError,
)
from app.modules.admission.domain.project_ideas import (
    ANALOG_WHERE,
    HELP_TAGS,
    HISTORY_KEEP,
    MAX_ANALOGS,
    MAX_CHALLENGES,
    MAX_PROJECTS,
    MAX_STEPS,
    WEEKS_MAX,
    WEEKS_MIN,
    Analog,
    Brief,
    ProjectIdea,
    ProjectRun,
    clean_brief,
)
from app.modules.admission.infrastructure.ai.prompts import project_ideas as prompt
from app.modules.admission.ports.ai import PromptSource, QuotaOf, StructuredAi
from app.modules.admission.ports.consent import AI, PurposeConsents
from app.modules.admission.ports.project_ideas import ProjectRunRepository
from app.modules.admission.ports.unit_of_work import UowFactory
from app.shared.ai_tasks import AiTask
from app.shared.brand import with_brand
from app.shared.clock import Clock
from app.shared.contracts.ai import AiInvalidOutputError
from app.shared.contracts.web_search import SearchCall, WebSearchGateway
from app.shared.ids import new_id
from app.shared.rate_limit import RateLimiter

import structlog

log = structlog.get_logger(__name__)

_WEEK: Final = 7 * 24 * 3600
_TOKENS: Final = 7000
_HITS: Final = 5
_MIN_PROJECTS: Final = 1
_KEY = re.compile(r"[^a-z0-9-]+")
_TITLE_MAX: Final = 120
_SUMMARY_MAX: Final = 600
_NAME_MAX: Final = 200
_LINE_MAX: Final = 300
_EFFECT_MAX: Final = 500


@dataclass(frozen=True, slots=True)
class RunSummary:
    """One earlier run in the history list."""

    id: UUID
    created_at: Any
    count: int


@dataclass(frozen=True, slots=True)
class RunOverview:
    """The newest run and a line per kept run."""

    latest: ProjectRun | None
    history: list[RunSummary]


def _line(value: Any, limit: int) -> str:
    return nfc(plain(value)).strip()[:limit] if isinstance(value, str) else ""


def _lines(values: Any, limit: int, keep: int) -> tuple[str, ...]:
    raw = values if isinstance(values, list) else []
    out = (_line(v, limit) for v in raw)
    return tuple(dict.fromkeys(v for v in out if v))[:keep]


def _analogs(values: Any, known: set[str]) -> tuple[Analog, ...]:
    out: list[Analog] = []
    for raw in (values if isinstance(values, list) else [])[:MAX_ANALOGS]:
        if not isinstance(raw, dict):
            continue
        name = _line(raw.get("name"), _NAME_MAX)
        where = raw.get("where")
        if not name or where not in ANALOG_WHERE:
            continue
        url = raw.get("url")
        out.append(
            Analog(
                name=name,
                where=where,
                url=url if isinstance(url, str) and url in known else None,
            )
        )
    return tuple(out)


def _weeks(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if WEEKS_MIN <= value <= WEEKS_MAX else None


def clean_ideas(data: Any, known: set[str]) -> tuple[ProjectIdea, ...]:
    """Keep valid, distinct projects; analog URLs only from the searched pages.

    Ideas that name their result, their measure and a way to start come first,
    so a vague one is the first to fall off the end of the list.
    """
    doc = data if isinstance(data, dict) else {}
    seen: set[str] = set()
    out: list[ProjectIdea] = []
    for raw in doc.get("projects") or []:
        if not isinstance(raw, dict):
            continue
        title = _line(raw.get("title"), _TITLE_MAX)
        summary = _line(raw.get("summary"), _SUMMARY_MAX)
        if not title or not summary or title.casefold() in seen:
            continue
        seen.add(title.casefold())
        key = _KEY.sub("-", _line(raw.get("key"), 60).lower()).strip("-")
        tags = raw.get("help_tags")
        taken = {p.key for p in out}
        out.append(
            ProjectIdea(
                key=key if key and key not in taken else f"p{len(out) + 1}",
                title=title,
                summary=summary,
                analogs=_analogs(raw.get("analogs"), known),
                challenges=_lines(raw.get("challenges"), _LINE_MAX, MAX_CHALLENGES),
                application_effect=_line(raw.get("application_effect"), _EFFECT_MAX),
                first_steps=_lines(raw.get("first_steps"), _LINE_MAX, MAX_STEPS),
                help_tags=tuple(
                    dict.fromkeys(
                        t
                        for t in (tags if isinstance(tags, list) else [])
                        if t in HELP_TAGS
                    )
                ),
                deliverable=_line(raw.get("deliverable"), _LINE_MAX),
                measure=_line(raw.get("measure"), _LINE_MAX),
                why_you=_line(raw.get("why_you"), _LINE_MAX),
                weeks=_weeks(raw.get("weeks")),
            )
        )
    if len(out) < _MIN_PROJECTS:
        raise AiInvalidOutputError()
    out.sort(key=lambda p: not p.complete)
    return tuple(out[:MAX_PROJECTS])


def search_queries(brief: Brief) -> list[str]:
    """Two web queries for projects that already exist: anywhere, then at home.

    They look for real things people built (the analogs), not for lists of
    ideas: such lists only return the generic topics the student already knows.
    """
    likes = " ".join(brief.likes.split())[:120]
    future = " ".join(brief.future_interest.split())[:120]
    mix = f"{likes} {future}".strip()
    return [
        f"{mix} project built by high school students results",
        f"{mix} Uzbekistan Tashkent initiative startup community",
    ]


ContextOf = Callable[[AdmissionContext], Awaitable[list[str]]]
_ITEMS_SHOWN: Final = 8


def student_context(uow_factory: UowFactory) -> ContextOf:
    """Read what the platform already knows: grade, fields, things already done.

    The lines join the brief, so an idea continues the student's real work
    and does not repeat an activity that already exists.
    """

    async def read(ctx: AdmissionContext) -> list[str]:
        async with uow_factory() as uow:
            focus = await load_study_focus(uow, ctx.user_id)
            items = await uow.items.list_for(ctx.user_id)
        lines: list[str] = []
        if ctx.grade is not None:
            lines.append(f"[school grade] {ctx.grade}")
        if focus.field_ids:
            lines.append(f"[chosen fields of study] {', '.join(focus.labels('en'))}")
        done = [
            " at ".join(p for p in (i.title.strip(), i.organization.strip()) if p)
            for i in items
            if i.kind == "activity" and i.title.strip()
        ][:_ITEMS_SHOWN]
        if done:
            lines.append(f"[already does] {'; '.join(done)}"[:900])
        return lines

    return read


def brief_lines(brief: Brief, locale: str) -> list[str]:
    """The model input about the student."""
    return [
        f"Language: {locale}",
        f"[likes] {brief.likes}",
        f"[future interest] {brief.future_interest}",
        f"[experience] {brief.experience}",
        f"[hours per day] {brief.hours_per_day}",
        f"[teammates] {brief.teammates} {brief.teammates_note}".strip(),
        f"[network] {brief.network}",
        f"[budget usd] {brief.budget_min_usd}-{brief.budget_max_usd}",
    ]


class ProjectIdeaService:
    """Generate, store and read project-idea runs of the student."""

    def __init__(
        self,
        runs: ProjectRunRepository,
        access: AccessPolicy,
        ai: StructuredAi,
        consents: PurposeConsents,
        prompts: PromptSource,
        clock: Clock,
        limiter: RateLimiter,
        weekly_limit: QuotaOf,
        *,
        web_search: WebSearchGateway | None = None,
        profile_of: Any = None,
        context_of: ContextOf | None = None,
    ) -> None:
        """Keep the collaborators and the reader of the soft weekly limit."""
        self._runs = runs
        self._access = access
        self._ai = ai
        self._consents = consents
        self._prompts = prompts
        self._clock = clock
        self._limiter = limiter
        self._limit = weekly_limit
        self._search = web_search
        self._profile_of = profile_of
        self._context_of = context_of

    async def _owner(self, ctx: AdmissionContext) -> None:
        res = await self._access.resolve(ctx, ctx.user_id)
        if not res.owner:
            raise AdmissionForbiddenError(params={"permission": "profile:edit"})

    async def generate(
        self, ctx: AdmissionContext, values: dict[str, Any], locale: str
    ) -> ProjectRun:
        """Validate the brief, spend the quota, ask the model, store the run."""
        brief = clean_brief(**values)
        await self._owner(ctx)
        granted = (await self._consents.granted([ctx.user_id])).get(
            ctx.user_id, frozenset()
        )
        if AI not in granted:
            raise ConsentRequiredError(params={"purpose": AI})
        limit = await self._limit(ctx.user_id)
        if limit is not None:
            await self._limiter.hit(
                f"admission:project_ideas:{ctx.user_id}",
                limit=limit,
                window_seconds=_WEEK,
            )
        sources, known = await self._web(brief, locale)
        about = await self._context_of(ctx) if self._context_of else []
        data, model = await self._ai.json(
            task=AiTask.ADMIT_PROJECT_IDEAS,
            system=with_brand(
                await self._prompts.text(AiTask.ADMIT_PROJECT_IDEAS, "system", locale)
            ),
            user=delimit(brief_lines(brief, locale) + about + sources),
            schema_name=prompt.SCHEMA_NAME,
            schema=prompt.SCHEMA,
            max_tokens=_TOKENS,
        )
        run = ProjectRun(
            id=new_id(),
            student_id=ctx.user_id,
            locale=locale,
            brief=brief,
            projects=clean_ideas(data, known),
            model=model,
            search_used=bool(known),
            created_at=self._clock.now(),
        )
        await self._runs.add(run, keep=HISTORY_KEEP)
        return run

    async def _web(self, brief: Brief, locale: str) -> tuple[list[str], set[str]]:
        """Search pages for analogs; a failed or missing search only means fewer."""
        if self._search is None or self._profile_of is None:
            return [], set()
        lines: list[str] = []
        known: set[str] = set()
        for query in search_queries(brief):
            try:
                reply = await self._search.search(
                    SearchCall(
                        query=query,
                        language=locale,
                        max_results=_HITS,
                        explain=False,
                        profile=self._profile_of(AiTask.ADMIT_PROJECT_IDEAS),
                    )
                )
            except Exception as exc:  # the web is extra context, never required
                log.info("project_ideas_search_failed", error=type(exc).__name__)
                continue
            for hit in reply.hits:
                if hit.url.startswith("https://") and hit.url not in known:
                    known.add(hit.url)
                    lines.append(f"[source {hit.url}] {hit.title}. {hit.snippet}"[:700])
        return lines, known

    async def overview(self, ctx: AdmissionContext) -> RunOverview:
        """The newest run and the kept history of the student."""
        await self._owner(ctx)
        runs: Sequence[ProjectRun] = await self._runs.history(
            ctx.user_id, limit=HISTORY_KEEP
        )
        return RunOverview(
            latest=runs[0] if runs else None,
            history=[RunSummary(r.id, r.created_at, len(r.projects)) for r in runs],
        )

    async def get(self, ctx: AdmissionContext, run_id: UUID) -> ProjectRun:
        """One of the student's own runs; anything else is not found."""
        await self._owner(ctx)
        run = await self._runs.get(ctx.user_id, run_id)
        if run is None:
            raise AdmissionNotFoundError()
        return run
