"""Job `notebooks.refresh_summaries`: notebook title, emoji and summary (§ 3.2.6)."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final
from uuid import UUID

from app.modules.notebooks.application.light_json import LightJson
from app.modules.notebooks.application.locale import LocaleResolver
from app.modules.notebooks.application.notebook_state import selection_hash
from app.modules.notebooks.domain.entities import (
    CachedSummary,
    Notebook,
    Source,
    SourceGuide,
)
from app.modules.notebooks.domain.enums import GuideStatus, SummaryStatus
from app.modules.notebooks.domain.errors import LimitReachedError, OutputInvalidError
from app.modules.notebooks.domain.guide import (
    SUMMARY_SCHEMA_NAME,
    ParsedSummary,
    parse_summary,
    summary_schema,
)
from app.modules.notebooks.domain.language import resolve_language
from app.modules.notebooks.domain.limits import STUCK_SOURCE_MINUTES
from app.modules.notebooks.domain.prompts.guide import (
    summary_system_prompt,
    summary_user_message,
)
from app.modules.notebooks.ports.unit_of_work import NotebooksUnitOfWork, UowFactory
from app.shared.ai_tasks import AiTask
from app.shared.clock import Clock
from app.shared.contracts.ai import AiInvalidOutputError, AiProviderError

import structlog

log = structlog.get_logger(__name__)

BATCH: Final = 20
SUMMARY_MAX_TOKENS: Final = 1200
RECHECK_SECONDS: Final = 60
SETTLED_GUIDES = (GuideStatus.READY, GuideStatus.FAILED)


@dataclass(frozen=True, slots=True)
class _Job:
    """A notebook whose summary is being built."""

    notebook_id: UUID
    owner_id: UUID
    digest: str
    guides: list[tuple[str, SourceGuide]]
    course: bool = False  # a course workspace: the course pool pays


class RefreshSummaries:
    """Builds the summaries that came due (cron every minute, 20 at a time)."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        clock: Clock,
        light: LightJson,
        locale: LocaleResolver,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.light = light
        self.locale = locale

    async def execute(self) -> int:
        """Rebuild the due summaries; return how many notebooks got a new one."""
        rebuilt = 0
        for job in await self._triage():
            if await self._build(job):
                rebuilt += 1
        return rebuilt

    # - - - Deciding what to build - - -

    async def _triage(self) -> list[_Job]:
        """Settle what needs no model call and mark the others `building`."""
        now = self.clock.now()
        jobs: list[_Job] = []
        async with self.uow_factory() as uow:
            for notebook in await uow.notebooks.due_summaries(now, BATCH):
                job = await self._decide(uow, notebook, now)
                await uow.notebooks.save(notebook)
                if job is not None:
                    jobs.append(job)
            await uow.commit()
        return jobs

    async def _decide(
        self, uow: NotebooksUnitOfWork, notebook: Notebook, now: datetime
    ) -> _Job | None:
        """Update the notebook's state; return a job when the model must be asked."""
        # Every state written here is stamped: `sweep_stuck` resets a `building`
        # summary whose `updated_at` is older than 10 minutes.
        notebook.updated_at = now
        sources = await uow.sources.list_for_notebook(notebook.id)
        chosen = [s for s in sources if s.selected and s.usable]
        if not chosen:
            _set_state(notebook, SummaryStatus.NONE, None)
            return None
        if not all(_settled(s, now) for s in chosen):
            _set_state(
                notebook,
                SummaryStatus.STALE,
                now + timedelta(seconds=RECHECK_SECONDS),
            )
            return None
        digest = selection_hash(sources)
        if digest == notebook.summary_hash and notebook.summary is not None:
            _set_state(notebook, SummaryStatus.READY, None)
            return None
        guides = [(s.title, s.guide) for s in chosen if s.guide is not None]
        if not guides:
            _set_state(notebook, SummaryStatus.FAILED, None)
            return None
        _set_state(notebook, SummaryStatus.BUILDING, notebook.summary_due_at)
        return _Job(
            notebook.id,
            notebook.owner_id,
            digest,
            guides,
            course=notebook.is_course_workspace,
        )

    # - - - Building - - -

    async def _build(self, job: _Job) -> bool:
        """Reuse the summary of the same texts, else ask the light model once."""
        language = resolve_language(None, await self.locale.locale_of(job.owner_id))
        parsed = await self._cached(job.digest, language)
        if parsed is None:
            parsed = await self._ask(job, language)
            if parsed is not None:
                await self._remember(job.digest, language, parsed)
        return await self._apply(job, parsed)

    async def _cached(self, digest: str, language: str) -> ParsedSummary | None:
        """The summary kept for this set of texts in this language, if any."""
        async with self.uow_factory() as uow:
            found = await uow.shared.get_summary(digest, language, self.clock.now())
            await uow.commit()
        if found is None:
            return None
        return ParsedSummary(found.title, found.emoji, found.summary)

    async def _remember(
        self, digest: str, language: str, parsed: ParsedSummary
    ) -> None:
        """Keep the summary for every student who holds the same texts."""
        async with self.uow_factory() as uow:
            await uow.shared.save_summary(
                digest,
                language,
                CachedSummary(parsed.title, parsed.emoji, parsed.summary),
            )
            await uow.commit()

    async def _ask(self, job: _Job, language: str) -> ParsedSummary | None:
        """One light-model call; None when it failed."""
        try:
            data = await self.light.call(
                job.owner_id,
                task=AiTask.NOTEBOOK_SUMMARY,
                system=summary_system_prompt(language),
                user=summary_user_message(job.guides),
                schema_name=SUMMARY_SCHEMA_NAME,
                schema=summary_schema(),
                max_tokens=SUMMARY_MAX_TOKENS,
                course=job.course,
            )
            return parse_summary(data, self.clock.now())
        except (
            AiProviderError,
            AiInvalidOutputError,
            LimitReachedError,
            OutputInvalidError,
        ) as error:
            log.info(
                "notebooks_summary_failed",
                notebook_id=str(job.notebook_id),
                error=error.code,
            )
            return None

    async def _apply(self, job: _Job, parsed: ParsedSummary | None) -> bool:
        """Store the summary, unless the notebook changed while the model worked."""
        now = self.clock.now()
        async with self.uow_factory() as uow:
            notebook = await uow.notebooks.get_for_update(job.notebook_id)
            if (
                notebook is None
                or notebook.is_deleted
                or notebook.summary_status is not SummaryStatus.BUILDING
            ):
                return False
            sources = await uow.sources.list_for_notebook(job.notebook_id)
            notebook.updated_at = now
            stored = False
            if selection_hash(sources) != job.digest:
                _set_state(notebook, SummaryStatus.STALE, now)
            elif parsed is None:
                _set_state(notebook, SummaryStatus.FAILED, None)
            else:
                _store(notebook, parsed, job.digest)
                stored = True
            await uow.notebooks.save(notebook)
            await uow.commit()
        return stored


def _store(notebook: Notebook, parsed: ParsedSummary, digest: str) -> None:
    """Apply the summary; the title and emoji only while they are automatic."""
    if notebook.title_auto:
        notebook.title = parsed.title
    if notebook.emoji_auto and parsed.emoji:
        notebook.emoji = parsed.emoji
    notebook.summary = parsed.summary
    notebook.summary_hash = digest
    _set_state(notebook, SummaryStatus.READY, None)


def _set_state(
    notebook: Notebook, status: SummaryStatus, due_at: datetime | None
) -> None:
    notebook.summary_status = status
    notebook.summary_due_at = due_at


def _settled(source: Source, now: datetime) -> bool:
    """The guide is finished, or the source has waited too long for one."""
    if source.guide_status in SETTLED_GUIDES:
        return True
    return now - source.updated_at >= timedelta(minutes=STUCK_SOURCE_MINUTES)
