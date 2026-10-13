"""Use case: the job that generates one Studio output (§ 3.4.0, `generate_artifact`).

The job takes the row only from `queued`, calls the model outside any transaction
(one repair call, provider errors retried with backoff), counts every call in the
budget and writes the result and the status in one transaction, unless the student
canceled or deleted the output meanwhile.
"""

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import datetime
from functools import partial
from typing import Any, Final
from uuid import UUID

from app.modules.notebooks.application.artifact_cache import shared_entry
from app.modules.notebooks.application.artifact_engine import (
    ACTIVE,
    REVISE_MAX_TOKENS,
    artifact_error,
    common_options,
    ensure_fits,
    revise_changes,
    revision_estimate,
)
from app.modules.notebooks.application.artifact_tasks import task_for_kind
from app.modules.notebooks.application.budget import NotebookBudget
from app.modules.notebooks.application.context_builder import ContextBuilder
from app.modules.notebooks.application.course_context import (
    CourseContextLoader,
    step_id_of,
)
from app.modules.notebooks.application.faithfulness_check import FaithfulnessCheck
from app.modules.notebooks.application.llm import JsonCompletion, NotebookLlm
from app.modules.notebooks.application.locale import LocaleResolver
from app.modules.notebooks.application.quota import QuotaService
from app.modules.notebooks.domain.artifacts.handler import (
    ArtifactHandler,
    ProcessContext,
    ProcessedOutput,
)
from app.modules.notebooks.domain.artifacts.kind_support import expect_options
from app.modules.notebooks.domain.artifacts.kinds.slides import SlidesOptions
from app.modules.notebooks.domain.artifacts.registry import handler_for
from app.modules.notebooks.domain.context import ContextPack
from app.modules.notebooks.domain.entities import Artifact, Notebook
from app.modules.notebooks.domain.enums import (
    ArtifactFailure,
    ArtifactKind,
    ArtifactStatus,
)
from app.modules.notebooks.domain.errors import OutputInvalidError
from app.modules.notebooks.domain.language import detect_language, resolve_language
from app.modules.notebooks.domain.limits import ARTIFACT_TITLE_MAX_CHARS
from app.modules.notebooks.domain.modality import readable_by
from app.modules.notebooks.domain.prompts.course import (
    system_prompt_for,
    task_with_course,
)
from app.modules.notebooks.domain.prompts.slides_revise import (
    SLIDES_REVISE_SCHEMA_NAME,
    merge_revised,
    revise_schema,
    revise_system_prompt,
    revise_user_message,
)
from app.modules.notebooks.domain.prompts.slides_task import SlideFormat
from app.modules.notebooks.domain.prompts.studio import (
    is_thin,
    repair_message,
    thin_sources_note,
)
from app.modules.notebooks.domain.sources_block import render_sources_block
from app.modules.notebooks.domain.tokens import OUTPUT_WEIGHT, Usage
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.settings import Settings
from app.shared.ai_tasks import AiTask
from app.shared.clock import Clock
from app.shared.contracts.ai import AiInvalidOutputError, AiProviderError
from app.shared.notifications import NotificationDraft, NotificationType

import structlog
from pydantic import BaseModel

log = structlog.get_logger(__name__)

MIN_CONTENT_TOKENS: Final = 8  # about a sentence; thinner gives `no_content`
PROVIDER_RETRY_DELAYS: Final = (2.0, 6.0)  # seconds; two retries
SEED_MODULUS: Final = 2**31
NOT_JSON: Final = "the answer was not a JSON object that matches the schema"
NO_PREVIOUS: Final = "(no valid JSON was returned)"
UNCHANGED: Final = (
    "none of the slides named in `changes` came back; return the changed slides "
    "with the same ids"
)
# The model answered nothing usable or never ran: the daily count is given back.
RELEASING: Final = frozenset(
    {
        ArtifactFailure.PROVIDER_ERROR,
        ArtifactFailure.TIMEOUT,
        ArtifactFailure.NO_CONTENT,
        ArtifactFailure.LIMIT_REACHED,
    }
)

Apply = Callable[[Artifact, datetime], None]


class _Failure(Exception):
    """A generation that ends in `failed` with this code."""

    def __init__(
        self, code: ArtifactFailure, params: dict[str, Any] | None = None
    ) -> None:
        """Keep the machine code and the params of the message."""
        super().__init__(code.value)
        self.code = code
        self.params = params or {}


@dataclass(slots=True)
class _Run:
    """What a started generation knows about itself."""

    artifact: Artifact  # as claimed; its title tells whether it was renamed
    attempt: int
    usage: Usage = field(default_factory=Usage)
    model: str | None = None
    superseded: bool = False  # a retry queued the row again
    course: bool = False  # in a course workspace: the course pool pays


@dataclass(frozen=True, slots=True)
class _Plan:
    """Everything the model call and the post-processing need."""

    task: AiTask
    system: str
    messages: list[dict[str, Any]]
    schema_name: str
    schema: dict[str, Any]
    max_tokens: int
    estimate: int
    process: Callable[[dict[str, Any]], ProcessedOutput]
    sampled: bool
    source_map: dict[str, str]
    sources_text: str = ""  # the sources block; "" skips the faithfulness check


@dataclass(frozen=True, slots=True)
class _Revision:
    """The parent deck and the rules for merging the revised slides."""

    content: dict[str, Any]
    slides: list[dict[str, Any]]
    changed: frozenset[str]
    slide_format: SlideFormat
    labels: frozenset[str]
    title: str
    refs_index: dict[str, Any]


NO_SOURCES_TASK_NOTE = (
    "No sources are selected. Make the output from the focus text, the notebook "
    "title and general knowledge, and do not cite sources."
)


def _general_task(task: str, notebook: Notebook | None) -> str:
    """The task of an output made without sources, with the notebook's topic."""
    topic = f"Notebook title: {notebook.title}\n\n" if notebook is not None else ""
    return f"{NO_SOURCES_TASK_NOTE}\n\n{topic}{task}"


def _with_thin_note(task: str, pack: ContextPack) -> str:
    """Add the thin-sources note when the whole pack is about a page or less."""
    if not is_thin(pack.token_estimate):
        return task
    words = sum(len(p.text.split()) for s in pack.sources for p in s.passages)
    titles = [source.title for source in pack.sources]
    return f"{task}\n\n{thin_sources_note(words, titles)}"


def _pack_language(kind: ArtifactKind, pack: ContextPack) -> str | None:
    """The language of the sources, for a deck with `auto` language (§ 3.4.6)."""
    if kind is not ArtifactKind.SLIDES:
        return None
    return detect_language(
        "\n".join(p.text for p in source.passages) for source in pack.sources
    )


def _deck_language(slides: list[Any]) -> str | None:
    """The language a deck is written in (a revision keeps it)."""
    texts = (
        " ".join([str(s.get("title") or ""), *map(str, s.get("bullets") or [])])
        + " "
        + str(s.get("notes") or "")
        for s in slides
        if isinstance(s, dict)
    )
    return detect_language([" ".join(texts)])


def _process_fresh(
    handler: ArtifactHandler,
    options: BaseModel,
    ctx: ProcessContext,
    data: dict[str, Any],
) -> ProcessedOutput:
    """Validate and fix the model's document; it must fit in 512 KB."""
    output = handler.process(data, options, ctx)
    ensure_fits(output.content)
    return output


def _process_revision(revision: _Revision, data: dict[str, Any]) -> ProcessedOutput:
    """Put the revised slides into the parent deck; the others stay as they are."""
    raw = data.get("slides")
    if not isinstance(raw, list):
        raise OutputInvalidError(["`slides` must be a list of the changed slides"])
    merged = merge_revised(
        revision.slides,
        raw,
        set(revision.changed),
        slide_format=revision.slide_format,
        labels=set(revision.labels),
    )
    if merged == revision.slides:
        raise OutputInvalidError([UNCHANGED])
    content = {**revision.content, "slides": merged}
    ensure_fits(content)
    return ProcessedOutput(
        title=revision.title, content=content, refs_index=revision.refs_index
    )


def _repair_messages(
    messages: list[dict[str, Any]],
    previous: JsonCompletion | None,
    problems: list[str],
) -> list[dict[str, Any]]:
    """The same conversation plus the bad answer and what was wrong with it."""
    if previous is None:
        ask = repair_message(problems, NO_PREVIOUS)
        return [*messages, {"role": "user", "content": ask}]
    text = previous.text or json.dumps(previous.data, ensure_ascii=False)
    return [
        *messages,
        {"role": "assistant", "content": text},
        {"role": "user", "content": repair_message(problems, text)},
    ]


def _apply_usage(row: Artifact, run: _Run) -> None:
    """Write the tokens of every call made so far (also of a failed output)."""
    if run.model is None:
        return
    usage = run.usage
    row.model = run.model
    row.tokens_in = usage.input
    row.tokens_out = usage.output
    row.tokens_cached = usage.cached
    row.weighted = usage.weighted
    row.cost_micro = usage.cost_micro


def _apply_ready(
    run: _Run, plan: _Plan, output: ProcessedOutput, row: Artifact, now: datetime
) -> None:
    """Fill the row with the result."""
    if row.title == run.artifact.title:  # a rename meanwhile wins over the model
        title = " ".join(output.title.split())[:ARTIFACT_TITLE_MAX_CHARS]
        row.title = title or row.title
    row.content = output.content
    row.refs_index = output.refs_index
    row.sampled = plan.sampled
    row.source_map = plan.source_map
    _apply_usage(row, run)
    row.status = ArtifactStatus.READY
    row.error = None
    row.finished_at = now


def _apply_failed(run: _Run, failure: _Failure, row: Artifact, now: datetime) -> None:
    """Mark the row `failed` with the code and message key."""
    _apply_usage(row, run)
    row.status = ArtifactStatus.FAILED
    row.error = artifact_error(failure.code, failure.params)
    row.finished_at = now


def _ready_notification(row: Artifact) -> NotificationDraft:
    """The bell entry "your output is ready" (once per output, to who asked)."""
    return NotificationDraft(
        user_id=row.charged_to,
        type=NotificationType.NOTEBOOK_ARTIFACT_READY,
        payload={
            "notebook_id": str(row.notebook_id),
            "artifact_id": str(row.id),
            "kind": row.kind.value,
            "title": row.title,
        },
        dedupe_key=f"notebook_artifact_ready:{row.id}",
    )


class GenerateArtifact:
    """Runs `notebooks.generate_artifact(artifact_id)`; safe to run twice."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        llm: NotebookLlm,
        budget: NotebookBudget,
        quota: QuotaService,
        locale: LocaleResolver,
        context: ContextBuilder,
        clock: Clock,
        settings: Settings,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        course_context: CourseContextLoader | None = None,
        faithfulness: FaithfulnessCheck | None = None,
    ) -> None:
        """Store the collaborators; `sleep` is injected for the retry backoff.

        `faithfulness` checks fresh outputs against their sources before they are
        stored (`NOTEBOOKS__FAITHFULNESS_CHECK`); without it nothing is checked.

        `course_context` gives the outputs of a course workspace their course (the
        outline and, for a step, its draft); without it they get none.
        """
        self.uow_factory = uow_factory
        self.llm = llm
        self.budget = budget
        self.quota = quota
        self.locale = locale
        self.context = context
        self.clock = clock
        self.settings = settings
        self.sleep = sleep
        self.course_context = course_context or CourseContextLoader(None)
        self.faithfulness = faithfulness

    async def execute(self, artifact_id: UUID | str) -> None:
        """Generate the output; do nothing unless it is `queued`."""
        run = await self._claim(UUID(str(artifact_id)))
        if run is None:
            return
        try:
            await self._generate(run)
        except _Failure as failure:
            await self._fail(run, failure)
        except Exception as exc:
            log.error(
                "notebooks.artifact.crashed",
                artifact_id=str(run.artifact.id),
                error=type(exc).__name__,
            )
            await self._fail(run, _Failure(ArtifactFailure.PROVIDER_ERROR))
        finally:
            if not run.superseded:
                quota = self.quota.pool(run.course)
                await quota.finished(run.artifact.charged_to, run.artifact.id)

    # - - - State machine - - -

    async def _claim(self, artifact_id: UUID) -> _Run | None:
        """`queued` -> `generating`, once; any other state means nothing to do."""
        async with self.uow_factory() as uow:
            artifact = await uow.artifacts.get_for_update(artifact_id)
            if (
                artifact is None
                or artifact.deleted_at is not None
                or artifact.status is not ArtifactStatus.QUEUED
            ):
                return None
            now = self.clock.now()
            artifact.status = ArtifactStatus.GENERATING
            artifact.started_at = now
            artifact.attempts += 1
            artifact.updated_at = now
            await uow.artifacts.save(artifact)
            notebook = await uow.notebooks.get(artifact.notebook_id)
            await uow.commit()
        course = notebook is not None and notebook.is_course_workspace
        return _Run(artifact=artifact, attempt=artifact.attempts, course=course)

    async def _settle(self, run: _Run, apply: Apply, *, notify: bool = False) -> bool:
        """Write an outcome if this run still owns the row; False if it was dropped.

        A canceled or deleted output (or one a retry took over) keeps its state and
        the result is discarded.
        """
        async with self.uow_factory() as uow:
            row = await uow.artifacts.get_for_update(run.artifact.id)
            if (
                row is None
                or row.status is not ArtifactStatus.GENERATING
                or row.attempts != run.attempt
            ):
                run.superseded = row is not None and row.status in ACTIVE
                return False
            now = self.clock.now()
            apply(row, now)
            row.updated_at = now
            await uow.artifacts.save(row)
            if notify:
                uow.notify(_ready_notification(row))
            await uow.commit()
        return True

    async def _fail(self, run: _Run, failure: _Failure) -> None:
        """Write `failed`; give the daily count back when the model gave nothing."""
        written = await self._settle(run, partial(_apply_failed, run, failure))
        if written and failure.code in RELEASING:
            quota = self.quota.pool(run.course)
            await quota.release(run.artifact.charged_to, run.artifact.kind)

    async def _store(self, run: _Run, plan: _Plan, output: ProcessedOutput) -> None:
        """Write `ready` with the content and one notification; share the result."""
        apply = partial(_apply_ready, run, plan, output)
        if await self._settle(run, apply, notify=True):
            await self._share(run, plan, output)

    async def _share(self, run: _Run, plan: _Plan, output: ProcessedOutput) -> None:
        """Keep the output for every student who asks for the same thing.

        Best effort: a failure here must not turn a finished output into an error.
        """
        if run.artifact.cache_key is None:
            return
        title = " ".join(output.title.split())[:ARTIFACT_TITLE_MAX_CHARS]
        try:
            async with self.uow_factory() as uow:
                sources = await uow.sources.get_many(run.artifact.source_ids)
                entry = shared_entry(
                    artifact=run.artifact,
                    title=title or run.artifact.title,
                    content=output.content,
                    refs_index=output.refs_index,
                    source_map=plan.source_map,
                    sources=sources,
                    sampled=plan.sampled,
                    model=run.model,
                )
                if entry is not None:
                    await uow.shared.save_artifact(entry)
                    await uow.commit()
        except Exception as exc:  # noqa: BLE001 - the output is already stored
            log.warning(
                "notebooks.artifact.share_failed",
                artifact_id=str(run.artifact.id),
                error=type(exc).__name__,
            )

    # - - - Generation - - -

    async def _generate(self, run: _Run) -> None:
        """Plan the call, check the budget, ask the model, store the result."""
        changes = revise_changes(run.artifact)
        if changes is None:
            plan = await self._plan_fresh(run)
        else:
            plan = await self._plan_revision(run, changes)
        await self._check_budget(run, plan)
        output = await self._produce(run, plan)
        output = await self._checked(run, plan, output)
        await self._store(run, plan, output)

    async def _checked(
        self, run: _Run, plan: _Plan, output: ProcessedOutput
    ) -> ProcessedOutput:
        """The output after the faithfulness check (regenerated or marked)."""
        if self.faithfulness is None or not plan.sources_text:
            return output
        checked = await self.faithfulness.ensure(
            output, plan.sources_text, partial(self._regenerate, run, plan)
        )
        if checked.usage.weighted:
            pool = self.budget.pool(run.course)
            await pool.add(run.artifact.charged_to, checked.usage.weighted)
        return checked.output

    async def _regenerate(self, run: _Run, plan: _Plan) -> ProcessedOutput | None:
        """One more output for a failed check; None when that attempt fails."""
        try:
            return await self._produce(run, plan)
        except _Failure:
            return None

    async def _plan_fresh(self, run: _Run) -> _Plan:
        """The context pack, the prompt and the post-processing of a new output."""
        artifact = run.artifact
        handler = handler_for(artifact.kind)
        options = handler.parse_options(dict(artifact.options))
        cap = handler.input_cap_tokens(self.settings.notebooks.studio_context_tokens)
        modalities = self.settings.ai_profile(task_for_kind(artifact.kind)).modalities
        async with self.uow_factory() as uow:
            found = await uow.sources.get_many(artifact.source_ids)
            sources = [
                source
                for source in found
                if source.usable
                and source.notebook_id == artifact.notebook_id
                and readable_by(source, modalities)
            ]
            general = not artifact.source_ids  # asked for without sources
            if not sources and not general:
                raise _Failure(ArtifactFailure.NO_CONTENT)
            pack = await self.context.for_studio(
                uow,
                artifact.notebook_id,
                sources,
                prompt=artifact.prompt,
                cap_tokens=cap,
            )
            notebook = await uow.notebooks.get(artifact.notebook_id)
        if not general and pack.token_estimate < MIN_CONTENT_TOKENS:
            raise _Failure(ArtifactFailure.NO_CONTENT)
        if notebook is not None:
            course = await self.course_context.load(
                notebook, step_id=step_id_of(artifact.options)
            )
            pack = replace(pack, course=course)
        language = await self._language(
            options, artifact.charged_to, _pack_language(artifact.kind, pack)
        )
        ctx = ProcessContext(pack, language, artifact.id.int % SEED_MODULUS)
        ai_task = task_for_kind(artifact.kind)
        task = task_with_course(
            artifact.kind, handler.task_block(options, artifact.prompt), pack.course
        )
        if not general:
            task = _with_thin_note(task, pack)
        max_tokens = self.llm.max_tokens(ai_task, handler.max_tokens(options))
        block = render_sources_block(pack)
        return _Plan(
            task=ai_task,
            system=system_prompt_for(artifact.kind, language),
            messages=[
                self.llm.context_message(block, ai_task),
                {
                    "role": "user",
                    "content": _general_task(task, notebook) if general else task,
                },
            ],
            schema_name=handler.schema_name,
            schema=handler.strict_schema(),
            max_tokens=max_tokens,
            estimate=pack.token_estimate + max_tokens * OUTPUT_WEIGHT,
            process=partial(_process_fresh, handler, options, ctx),
            sampled=pack.sampled,
            source_map={label: str(sid) for label, sid in pack.source_map.items()},
            sources_text="" if general else block,
        )

    async def _plan_revision(self, run: _Run, changes: list[dict[str, str]]) -> _Plan:
        """Revise named slides: the deck and the changes go to the model, no sources."""
        artifact = run.artifact
        parent = None
        if artifact.parent_id is not None:
            async with self.uow_factory() as uow:
                parent = await uow.artifacts.get(artifact.parent_id)
        slides = (parent.content or {}).get("slides") if parent else None
        changed = frozenset(str(change.get("slide_id")) for change in changes)
        if (
            parent is None
            or not isinstance(slides, list)
            or not changed & {str(slide.get("id")) for slide in slides}
        ):
            raise _Failure(ArtifactFailure.NO_CONTENT)
        options = expect_options(
            handler_for(ArtifactKind.SLIDES).parse_options(dict(artifact.options)),
            SlidesOptions,
        )
        language = await self._language(
            options, artifact.charged_to, _deck_language(slides)
        )
        message = revise_user_message(slides, changes)
        revision = _Revision(
            content=dict(parent.content or {}),
            slides=slides,
            changed=changed,
            slide_format=options.format,
            labels=frozenset(parent.refs_index or {}),
            title=artifact.title,
            refs_index=dict(parent.refs_index or {}),
        )
        return _Plan(
            task=AiTask.STUDIO_SLIDES_REVISE,
            system=revise_system_prompt(language, options.format),
            messages=[{"role": "user", "content": message}],
            schema_name=SLIDES_REVISE_SCHEMA_NAME,
            schema=revise_schema(),
            max_tokens=self.llm.max_tokens(
                AiTask.STUDIO_SLIDES_REVISE, REVISE_MAX_TOKENS
            ),
            estimate=revision_estimate(len(message)),
            process=partial(_process_revision, revision),
            sampled=parent.sampled,
            source_map=dict(parent.source_map),
        )

    async def _language(
        self, options: BaseModel, owner_id: UUID, detected: str | None = None
    ) -> str:
        """`options.language`, else the `detected` one, else the owner's locale."""
        requested = common_options(options).language or detected
        locale = "" if requested else await self.locale.locale_of(owner_id)
        return resolve_language(requested, locale)

    async def _check_budget(self, run: _Run, plan: _Plan) -> None:
        """The budget may have run out while the job waited in the queue."""
        pool = self.budget.pool(run.course)
        hit = await pool.check(run.artifact.charged_to, plan.estimate)
        if hit is not None:
            raise _Failure(
                ArtifactFailure.LIMIT_REACHED,
                {"scope": hit.scope, "resets_at": hit.resets_at.isoformat()},
            )

    async def _produce(self, run: _Run, plan: _Plan) -> ProcessedOutput:
        """Ask the model; one repair call when the document breaks the rules."""
        previous: JsonCompletion | None = None
        problems: list[str] = []
        for attempt in range(2):
            messages = plan.messages
            if attempt:
                messages = _repair_messages(messages, previous, problems)
            try:
                done = await self._ask(run, plan, messages)
            except AiInvalidOutputError:
                previous, problems = None, [NOT_JSON]
                continue
            try:
                return plan.process(done.data)
            except OutputInvalidError as exc:
                previous, problems = done, exc.problems
        raise _Failure(ArtifactFailure.INVALID_OUTPUT)

    async def _ask(
        self, run: _Run, plan: _Plan, messages: list[dict[str, Any]]
    ) -> JsonCompletion:
        """One model call with a timeout; provider errors are retried with backoff."""
        retries = iter(PROVIDER_RETRY_DELAYS)
        while True:
            try:
                async with asyncio.timeout(self.settings.notebooks.llm_timeout_seconds):
                    done = await self.llm.json(
                        task=plan.task,
                        system=plan.system,
                        messages=messages,
                        schema_name=plan.schema_name,
                        schema=plan.schema,
                        max_tokens=plan.max_tokens,
                    )
            except AiProviderError:
                delay = next(retries, None)
                if delay is None:
                    raise _Failure(ArtifactFailure.PROVIDER_ERROR) from None
                await self.sleep(delay)
            except TimeoutError:
                raise _Failure(ArtifactFailure.TIMEOUT) from None
            else:
                run.usage = run.usage + done.usage
                run.model = done.model
                pool = self.budget.pool(run.course)
                await pool.add(run.artifact.charged_to, done.usage.weighted)
                return done
