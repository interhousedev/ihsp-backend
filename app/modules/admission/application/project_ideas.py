"""Project ideas for a student: two web searches, one model call, a kept history."""

import re
from collections.abc import Sequence
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


def clean_ideas(data: Any, known: set[str]) -> tuple[ProjectIdea, ...]:
    """Keep valid, distinct projects; analog URLs only from the searched pages."""
    doc = data if isinstance(data, dict) else {}
    seen: set[str] = set()
    out: list[ProjectIdea] = []
    for raw in (doc.get("projects") or [])[:MAX_PROJECTS]:
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
            )
        )
    if len(out) < _MIN_PROJECTS:
        raise AiInvalidOutputError()
    return tuple(out)


def search_queries(brief: Brief) -> list[str]:
    """Two web queries: ideas for the interests, and the same in Uzbekistan."""
    likes = " ".join(brief.likes.split())[:120]
    experience = " ".join(brief.experience.split())[:80]
    return [
        f"{likes} {experience} student project ideas".strip(),
        f"{likes} student project Uzbekistan",
    ]


def brief_lines(brief: Brief, locale: str) -> list[str]:
    """The model input about the student."""
    return [
        f"Language: {locale}",
        f"[likes] {brief.likes}",
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
        data, model = await self._ai.json(
            task=AiTask.ADMIT_PROJECT_IDEAS,
            system=with_brand(
                await self._prompts.text(AiTask.ADMIT_PROJECT_IDEAS, "system", locale)
            ),
            user=delimit(brief_lines(brief, locale) + sources),
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
