"""Prompt studio: counselors edit, test and activate the essay-reviewer prompts."""

import dataclasses
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.essay_review_core import (
    load_uni_context,
    run_base_review,
    run_check,
    run_feedback,
    run_uni_review,
)
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
)
from app.modules.admission.domain.essay_reviews import EssayInput, UniContext
from app.modules.admission.domain.permissions import KIND_ROLE, Permission
from app.modules.admission.domain.prompt_studio import (
    DAILY_RUNS,
    MAX_PROMPT_CONTEXT_CHARS,
    MAX_SAMPLE_CHARS,
    MAX_SAMPLES,
    SLOTS,
    WINDOW_SECONDS,
    PromptIssue,
    PromptVersionInfo,
    RunDelta,
    SampleInput,
    SlotState,
    StudioRun,
    StudioSlot,
    blocking,
    delta_of,
    find_slot,
)
from app.modules.admission.ports.ai import PromptSource, StructuredAi
from app.modules.admission.ports.prompt_studio import PromptStudioAdmin
from app.modules.admission.ports.unit_of_work import UowFactory
from app.shared.actor import Role
from app.shared.ai_tasks import AiTask
from app.shared.base_error import ValidationFailedError
from app.shared.clock import Clock
from app.shared.rate_limit import RateLimiter

UniLoader = Callable[[Any, UUID], Awaitable["UniContext | None"]]


async def _default_per_day() -> int | None:
    """The built-in daily run limit, used when no runtime source is wired."""
    return DAILY_RUNS


class OverridePrompts:
    """A prompt source that answers one slot with a draft and the rest as usual."""

    def __init__(self, base: PromptSource, task: AiTask, name: str, text: str) -> None:
        """Keep the real source and the draft for one slot."""
        self._base = base
        self._task = task
        self._name = name
        self._text = text

    async def text(self, task: AiTask, name: str, locale: str) -> str:
        """The draft for the slot under test, else the normal text."""
        if task == self._task and name == self._name:
            return self._text
        return await self._base.text(task, name, locale)


class StudioRunner(Protocol):
    """Runs one reviewer slot on an essay with a given prompt source."""

    async def run(
        self,
        slot: StudioSlot,
        *,
        prompts: PromptSource,
        essay: EssayInput,
        uni: "UniContext | None",
        locale: str,
    ) -> StudioRun:
        """Run the slot and return the serialised result."""
        ...


class CoreStudioRunner:
    """Runs the slots through the shared essay-review core."""

    def __init__(self, ai: StructuredAi) -> None:
        """Keep the structured-output model gateway."""
        self._ai = ai

    async def run(
        self,
        slot: StudioSlot,
        *,
        prompts: PromptSource,
        essay: EssayInput,
        uni: "UniContext | None",
        locale: str,
    ) -> StudioRun:
        """Run the slot and return the serialised result."""
        ai = self._ai
        result: Any
        if slot.kind == "base":
            result, model = await run_base_review(
                ai, prompts, essay=essay, exemplars=(), locale=locale
            )
        elif slot.kind == "uni":
            assert uni is not None  # the service loads it for uni slots
            result, model = await run_uni_review(
                ai, prompts, essay=essay, uni=uni, base=None, locale=locale
            )
        elif slot.kind == "check":
            result, model = await run_check(ai, prompts, essay=essay, locale=locale)
        else:
            result, model = await run_feedback(ai, prompts, essay=essay, locale=locale)
        return StudioRun(model=model, output=dataclasses.asdict(result))


@dataclass(frozen=True, slots=True)
class SampleResult:
    """The draft and active runs on one sample."""

    label: str
    exemplar_id: UUID | None
    active: StudioRun
    draft: StudioRun
    delta: RunDelta


@dataclass(frozen=True, slots=True)
class StudioReport:
    """A draft compared with the active prompt on every sample."""

    warnings: tuple[PromptIssue, ...]
    results: tuple[SampleResult, ...]


@dataclass(frozen=True, slots=True)
class SavedVersion:
    """A stored version with the non-blocking findings on its text."""

    version: PromptVersionInfo
    warnings: tuple[PromptIssue, ...]


@dataclass(frozen=True, slots=True)
class _Sample:
    label: str
    exemplar_id: UUID | None
    essay: EssayInput


def _invalid(field: str, **extra: Any) -> ValidationFailedError:
    return ValidationFailedError(params={"field": field, **extra})


class PromptStudioService:
    """Staff use cases of the prompt studio; every one needs the edit permission."""

    def __init__(
        self,
        admin: PromptStudioAdmin,
        runner: StudioRunner,
        prompts: PromptSource,
        uow_factory: UowFactory,
        clock: Clock,
        limiter: RateLimiter,
        *,
        uni_loader: UniLoader = load_uni_context,
        per_day: Callable[[], Awaitable[int | None]] | None = None,
    ) -> None:
        """Keep the registry port, the runner, the sources and the daily limit."""
        self._admin = admin
        self._runner = runner
        self._prompts = prompts
        self._uow = uow_factory
        self._clock = clock
        self._limiter = limiter
        self._uni_loader = uni_loader
        self._per_day = per_day or _default_per_day

    def can_edit(self, ctx: AdmissionContext) -> bool:
        """Return whether the caller is an administrator or holds the edit grant."""
        if Role.ADMIN in ctx.actor.roles:
            return True
        now = self._clock.now()
        return any(
            a.active_at(now)
            and KIND_ROLE.get(a.role.kind) in ctx.actor.roles
            and Permission.ESSAY_PROMPTS_EDIT in a.role.permissions
            for a in ctx.assignments
        )

    def _require(self, ctx: AdmissionContext, task: str, name: str) -> StudioSlot:
        if not self.can_edit(ctx):
            raise AdmissionForbiddenError(
                params={"permission": Permission.ESSAY_PROMPTS_EDIT.value}
            )
        slot = find_slot(task, name)
        if slot is None:
            raise AdmissionNotFoundError()
        return slot

    async def slots(self, ctx: AdmissionContext) -> list[SlotState]:
        """The four slots with their active text; unregistered ones are skipped."""
        if not self.can_edit(ctx):
            raise AdmissionForbiddenError(
                params={"permission": Permission.ESSAY_PROMPTS_EDIT.value}
            )
        out: list[SlotState] = []
        for slot in SLOTS:
            if await self._admin.info(slot) is not None:
                out.append(await self._admin.state(ctx.actor, slot, ""))
        return out

    async def slot(
        self, ctx: AdmissionContext, task: str, name: str, locale: str
    ) -> SlotState:
        """One slot with the text in force for a locale and its history."""
        slot = self._require(ctx, task, name)
        return await self._admin.state(ctx.actor, slot, locale)

    async def save(
        self,
        ctx: AdmissionContext,
        task: str,
        name: str,
        *,
        text: str,
        locale: str,
        note: str,
    ) -> SavedVersion:
        """Validate a draft and store it as the new active version."""
        slot = self._require(ctx, task, name)
        issues = await self._admin.check(slot, text)
        if blocking(issues):
            raise _invalid("text", issues=[i.code for i in blocking(issues)])
        version = await self._admin.put_version(
            ctx.actor, slot, text=text, locale=locale, note=note
        )
        return SavedVersion(version, issues)

    async def activate(
        self, ctx: AdmissionContext, task: str, name: str, version: int
    ) -> PromptVersionInfo:
        """Make a stored version the active one."""
        slot = self._require(ctx, task, name)
        return await self._admin.activate(ctx.actor, slot, version)

    async def revert(
        self, ctx: AdmissionContext, task: str, name: str, locale: str
    ) -> None:
        """Return the slot to its built-in text."""
        slot = self._require(ctx, task, name)
        await self._admin.revert(ctx.actor, slot, locale)

    async def test(
        self,
        ctx: AdmissionContext,
        task: str,
        name: str,
        *,
        text: str,
        samples: list[SampleInput],
        locale: str,
        institution_id: UUID | None = None,
    ) -> StudioReport:
        """Run the draft and the active prompt on each sample and compare."""
        slot = self._require(ctx, task, name)
        if slot.kind == "uni" and institution_id is None:
            raise _invalid("institution_id")
        if not 1 <= len(samples) <= MAX_SAMPLES:
            raise _invalid("samples", max=MAX_SAMPLES)
        issues = await self._admin.check(slot, text)
        if blocking(issues):
            raise _invalid("text", issues=[i.code for i in blocking(issues)])
        async with self._uow() as uow:
            resolved = [await self._resolve(uow, s) for s in samples]
            uni = await self._load_uni(uow, slot, institution_id)
        await self._charge(ctx, len(resolved))

        draft_source = OverridePrompts(self._prompts, slot.task, slot.name, text)
        results: list[SampleResult] = []
        for item in resolved:
            active = await self._runner.run(
                slot, prompts=self._prompts, essay=item.essay, uni=uni, locale=locale
            )
            draft = await self._runner.run(
                slot, prompts=draft_source, essay=item.essay, uni=uni, locale=locale
            )
            results.append(
                SampleResult(
                    label=item.label,
                    exemplar_id=item.exemplar_id,
                    active=active,
                    draft=draft,
                    delta=delta_of(active.output, draft.output),
                )
            )
        return StudioReport(warnings=issues, results=tuple(results))

    async def _load_uni(
        self, uow: Any, slot: Any, institution_id: UUID | None
    ) -> UniContext | None:
        if slot.kind != "uni":
            return None
        assert institution_id is not None
        uni = await self._uni_loader(uow, institution_id)
        if uni is None:
            raise AdmissionNotFoundError()
        return uni

    async def _charge(self, ctx: AdmissionContext, hits: int) -> None:
        per_day = await self._per_day()
        if per_day is None:
            return
        for _ in range(hits):
            await self._limiter.hit(
                f"admission:prompt_studio:{ctx.user_id}",
                limit=per_day,
                window_seconds=WINDOW_SECONDS,
            )

    async def _resolve(self, uow: Any, sample: SampleInput) -> _Sample:
        has_text = sample.text is not None
        if has_text == (sample.exemplar_id is not None):
            raise _invalid("samples")
        context = sample.prompt_text
        if len(context) > MAX_PROMPT_CONTEXT_CHARS:
            raise _invalid("prompt_text", max=MAX_PROMPT_CONTEXT_CHARS)
        if sample.text is not None:
            body = sample.text.strip()
            if not body or len(body) > MAX_SAMPLE_CHARS:
                raise _invalid("text", max=MAX_SAMPLE_CHARS)
            return _Sample(
                "pasted",
                None,
                EssayInput(sample.kind, "", context, None, body),
            )
        found = await uow.exemplars.get(sample.exemplar_id)
        if found is None:
            raise AdmissionNotFoundError()
        return _Sample(
            found.title or "exemplar",
            found.id,
            EssayInput(found.kind, found.title, found.prompt, None, found.body),
        )
