"""Job `notebooks.label_sources`: topic labels for the selected sources (G12/G13)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

from app.modules.notebooks.application.light_json import LightJson
from app.modules.notebooks.application.locale import LocaleResolver
from app.modules.notebooks.domain.errors import LimitReachedError, OutputInvalidError
from app.modules.notebooks.domain.label_output import (
    LABELS_SCHEMA_NAME,
    ParsedLabels,
    labels_schema,
    parse_labels,
)
from app.modules.notebooks.domain.label_plan import plan_labels
from app.modules.notebooks.domain.labels import (
    ERROR_INVALID_OUTPUT,
    ERROR_LIMIT_REACHED,
    ERROR_NOTHING_TO_LABEL,
    ERROR_PROVIDER,
    LabelOrigin,
    LabelRun,
    LabelRunStatus,
)
from app.modules.notebooks.domain.language import resolve_language
from app.modules.notebooks.domain.prompts.labels import (
    LabelInput,
    labels_system_prompt,
    labels_user_message,
    source_key,
)
from app.modules.notebooks.ports.unit_of_work import NotebooksUnitOfWork, UowFactory
from app.shared.ai_tasks import AiTask
from app.shared.clock import Clock
from app.shared.contracts.ai import AiInvalidOutputError, AiProviderError
from app.shared.ids import new_id

import structlog

log = structlog.get_logger(__name__)

LABELS_MAX_TOKENS: Final = 1500


@dataclass(frozen=True, slots=True)
class _Job:
    """What the model call needs, read before it starts."""

    notebook_id: UUID
    user_id: UUID  # who clicked: pays and reads the labels
    started_at: datetime
    course: bool  # a course workspace: the course pool pays
    sources: dict[str, UUID]  # prompt key -> source id
    items: list[LabelInput]
    existing: list[str]  # names of the student's own labels


class LabelSources:
    """Asks the light model for topics and writes labels and links in one step."""

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

    async def execute(self, notebook_id: UUID) -> None:
        """Run the labeling that `StartLabeling` queued; a failure only marks it.

        Nothing is written unless the answer is usable; a run that is no longer the
        notebook's current one (it timed out and another started) writes nothing.
        """
        job = await self._read(notebook_id)
        if job is None:
            return
        try:
            parsed = await self._ask(job)
        except LimitReachedError as error:
            await self._fail(job, ERROR_LIMIT_REACHED, error.code)
        except AiProviderError as error:
            await self._fail(job, ERROR_PROVIDER, error.code)
        except (AiInvalidOutputError, OutputInvalidError) as error:
            await self._fail(job, ERROR_INVALID_OUTPUT, error.code)
        else:
            await self._apply(job, parsed)

    async def _read(self, notebook_id: UUID) -> _Job | None:
        """The sources and the student's labels; None when there is nothing to do."""
        async with self.uow_factory() as uow:
            notebook = await uow.notebooks.get(notebook_id)
            run = await uow.labels.get_run(notebook_id)
            if (
                notebook is None
                or notebook.is_deleted
                or run is None
                or run.status is not LabelRunStatus.RUNNING
                or run.started_at is None
            ):
                return None
            chosen = [
                source
                for source in await uow.sources.list_for_notebook(notebook_id)
                if source.selected and source.usable
            ]
            if not chosen:
                await self._save_end(
                    uow, run, LabelRunStatus.FAILED, ERROR_NOTHING_TO_LABEL
                )
                await uow.commit()
                return None
            labels = await uow.labels.list_for_notebook(notebook_id)
        return _Job(
            notebook_id=notebook_id,
            user_id=run.started_by or notebook.owner_id,
            started_at=run.started_at,
            course=notebook.is_course_workspace,
            sources={source_key(i): s.id for i, s in enumerate(chosen)},
            items=[LabelInput(s.title, s.guide) for s in chosen],
            existing=[
                label.name for label in labels if label.origin is LabelOrigin.MANUAL
            ],
        )

    async def _ask(self, job: _Job) -> ParsedLabels:
        """One light-model call and the repaired answer."""
        language = resolve_language(None, await self.locale.locale_of(job.user_id))
        data = await self.light.call(
            job.user_id,
            task=AiTask.SOURCE_LABELS,
            system=labels_system_prompt(language),
            user=labels_user_message(job.items, job.existing),
            schema_name=LABELS_SCHEMA_NAME,
            schema=labels_schema(),
            max_tokens=LABELS_MAX_TOKENS,
            course=job.course,
        )
        return parse_labels(data, job.sources)

    async def _current(self, uow: NotebooksUnitOfWork, job: _Job) -> LabelRun | None:
        """The run row while it is still this job's (the notebook is locked)."""
        notebook = await uow.notebooks.get_for_update(job.notebook_id)
        if notebook is None or notebook.is_deleted:
            return None
        run = await uow.labels.get_run(job.notebook_id)
        if (
            run is None
            or run.status is not LabelRunStatus.RUNNING
            or run.started_at != job.started_at
        ):
            return None
        return run

    async def _save_end(
        self,
        uow: NotebooksUnitOfWork,
        run: LabelRun,
        status: LabelRunStatus,
        error: str | None,
    ) -> None:
        run.status = status
        run.finished_at = self.clock.now()
        run.error = error
        await uow.labels.save_run(run)

    async def _fail(self, job: _Job, reason: str, code: str) -> None:
        """Mark the run failed; labels and links stay as they were."""
        log.info(
            "notebooks_labels_failed",
            notebook_id=str(job.notebook_id),
            reason=reason,
            error=code,
        )
        async with self.uow_factory() as uow:
            run = await self._current(uow, job)
            if run is not None:
                await self._save_end(uow, run, LabelRunStatus.FAILED, reason)
                await uow.commit()

    async def _apply(self, job: _Job, parsed: ParsedLabels) -> None:
        """Merge the answer into the notebook and end the run, in one transaction."""
        async with self.uow_factory() as uow:
            run = await self._current(uow, job)
            if run is None:
                return
            alive = {s.id for s in await uow.sources.list_for_notebook(job.notebook_id)}
            plan = plan_labels(
                notebook_id=job.notebook_id,
                labels=await uow.labels.list_for_notebook(job.notebook_id),
                links=await uow.labels.links_for_notebook(job.notebook_id),
                parsed=parsed,
                sources={k: v for k, v in job.sources.items() if v in alive},
                now=self.clock.now(),
                new_id=new_id,
            )
            await uow.labels.delete_links(plan.unlink_auto_of, LabelOrigin.AUTO)
            await uow.labels.delete(plan.delete_labels)
            for label in plan.new_labels:
                await uow.labels.add(label)
            await uow.labels.add_links(plan.new_links)
            await self._save_end(uow, run, LabelRunStatus.IDLE, None)
            await uow.commit()
