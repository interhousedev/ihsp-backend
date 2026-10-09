"""Job `notebooks.build_source_guide`: summary, key topics and questions (§ 3.2.5)."""

import asyncio
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from app.modules.notebooks.application.light_json import LightJson, Sleep
from app.modules.notebooks.application.locale import LocaleResolver
from app.modules.notebooks.domain.context_policy import evenly_spaced
from app.modules.notebooks.domain.entities import SourceGuide
from app.modules.notebooks.domain.enums import GuideStatus, SourceStatus
from app.modules.notebooks.domain.errors import LimitReachedError, OutputInvalidError
from app.modules.notebooks.domain.guide import (
    GUIDE_SCHEMA_NAME,
    guide_schema,
    parse_guide,
)
from app.modules.notebooks.domain.language import resolve_language
from app.modules.notebooks.domain.prompts.guide import (
    guide_system_prompt,
    guide_user_message,
)
from app.modules.notebooks.ports.guide_lock import GuideLock
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.ai_tasks import AiTask
from app.shared.clock import Clock
from app.shared.contracts.ai import AiInvalidOutputError, AiProviderError

import structlog

log = structlog.get_logger(__name__)

GUIDE_INPUT_TOKENS: Final = 30_000
GUIDE_MAX_TOKENS: Final = 800
GUIDE_PASSAGE_SEPARATOR: Final = "\n\n"
USABLE = (SourceStatus.READY, SourceStatus.STALE)
WAIT_STEP_SECONDS: Final = 3.0
WAIT_STEPS: Final = 15  # another worker has 45 s to write the shared guide


@dataclass(frozen=True, slots=True)
class _Job:
    """What the model call needs, read before it starts."""

    source_id: UUID
    owner_id: UUID
    title: str
    content_hash: str | None
    document_id: UUID | None
    course: bool = False  # a source of a course workspace: the course pool pays


class BuildSourceGuide:
    """Writes the guide of a ready source; a failure never fails the source."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        clock: Clock,
        light: LightJson,
        locale: LocaleResolver,
        lock: GuideLock,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.light = light
        self.locale = locale
        self.lock = lock
        self.sleep = sleep

    async def execute(self, source_id: UUID) -> None:
        """Build the guide unless the source is not usable or already has one.

        A guide belongs to the text, not to the student: it is looked up by
        (document, language) first, and written at most once for all students who
        hold the same text (the others wait a moment for it).
        """
        job = await self._start(source_id)
        if job is None:
            return
        language = resolve_language(None, await self.locale.locale_of(job.owner_id))
        guide = await self._shared(job, language)
        if guide is None:
            guide = await self._write(job, language)
        await self._finish(source_id, job.content_hash, guide)

    async def _shared(self, job: _Job, language: str) -> SourceGuide | None:
        """The guide written for this text and language, if there is one."""
        if job.document_id is None:
            return None
        async with self.uow_factory() as uow:
            return await uow.documents.get_guide(job.document_id, language)

    async def _write(self, job: _Job, language: str) -> SourceGuide | None:
        """Ask the model once for the text; wait for it if a worker already does."""
        token: str | None = None
        if job.document_id is not None:
            token = await self.lock.try_claim(job.document_id, language)
            if token is None:
                waited = await self._wait_for_shared(job, language)
                if waited is not None:
                    return waited
        try:
            guide = await self._ask(job, language)
            if guide is not None and job.document_id is not None:
                async with self.uow_factory() as uow:
                    await uow.documents.save_guide(job.document_id, language, guide)
                    await uow.commit()
            return guide
        finally:
            if token is not None and job.document_id is not None:
                await self.lock.release(job.document_id, language, token)

    async def _wait_for_shared(self, job: _Job, language: str) -> SourceGuide | None:
        """Poll for the guide another worker is writing (up to 45 seconds)."""
        for _ in range(WAIT_STEPS):
            await self.sleep(WAIT_STEP_SECONDS)
            guide = await self._shared(job, language)
            if guide is not None:
                return guide
        return None

    async def _ask(self, job: _Job, language: str) -> SourceGuide | None:
        """One light-model call; None when it failed (never fails the source)."""
        async with self.uow_factory() as uow:
            passages = await uow.passages.list_for_sources([job.source_id])
        picked = evenly_spaced(passages, GUIDE_INPUT_TOKENS)
        text = GUIDE_PASSAGE_SEPARATOR.join(p.text for p in picked)
        try:
            data = await self.light.call(
                job.owner_id,
                task=AiTask.SOURCE_GUIDE,
                system=guide_system_prompt(language),
                user=guide_user_message(job.title, text),
                schema_name=GUIDE_SCHEMA_NAME,
                schema=guide_schema(),
                max_tokens=GUIDE_MAX_TOKENS,
                course=job.course,
            )
            return parse_guide(data)
        except (
            AiProviderError,
            AiInvalidOutputError,
            LimitReachedError,
            OutputInvalidError,
        ) as error:
            log.info(
                "notebooks_guide_failed",
                document_id=str(job.document_id),
                error=error.code,
            )
            return None

    async def _start(self, source_id: UUID) -> _Job | None:
        """Mark the guide `building` and pick the text the model reads."""
        async with self.uow_factory() as uow:
            source = await uow.sources.get_for_update(source_id)
            if (
                source is None
                or source.status not in USABLE
                or source.guide_status is GuideStatus.READY
            ):
                return None
            if source.passage_count == 0:
                return None
            source.guide_status = GuideStatus.BUILDING
            source.updated_at = self.clock.now()
            await uow.sources.save(source)
            notebook = await uow.notebooks.get(source.notebook_id)
            await uow.commit()
        return _Job(
            source_id=source_id,
            owner_id=source.owner_id,
            title=source.title,
            content_hash=source.content_hash,
            document_id=source.document_id,
            course=notebook is not None and notebook.is_course_workspace,
        )

    async def _finish(
        self, source_id: UUID, content_hash: str | None, guide: SourceGuide | None
    ) -> None:
        """Store the guide (or the failure) unless the text changed meanwhile."""
        async with self.uow_factory() as uow:
            source = await uow.sources.get_for_update(source_id)
            if (
                source is None
                or source.status not in USABLE
                or source.content_hash != content_hash
            ):
                return  # deleted or reprocessed: the new run builds its own guide
            source.guide = guide
            source.guide_status = (
                GuideStatus.READY if guide is not None else GuideStatus.FAILED
            )
            source.updated_at = self.clock.now()
            await uow.sources.save(source)
            await uow.commit()
