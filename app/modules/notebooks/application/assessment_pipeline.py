"""Plan-then-generate quizzes and flash cards: profile, mode, blueprint, check.

1. Profile: a cheap model says what each source is (AI task STUDIO_SOURCE_PROFILE);
   rules guess when it cannot run.
2. Mode: the requested one, else read from the focus text, else from the profiles.
3. Blueprint: a cheap planner proposes slots (STUDIO_ASSESSMENT_PLAN); code keeps
   the exact count and the template quota.
4. Batches: the kind's own task (STUDIO_QUIZ / STUDIO_FLASHCARDS) writes the items
   of a blueprint slice under hard self-containment rules.
5. Check: code rules (unseen passages, stimulus, duplicates, the kind's validation)
   and a cheap solver without sources (STUDIO_ITEM_VERIFY); rejected slots are
   written again, up to `assessment_fill_rounds` more times.

Profile, plan and check are best effort: a failure falls back to rules.
"""

import random
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from functools import partial
from typing import Any, Final, cast

from app.modules.notebooks.application.exercise_pipeline import (
    ExerciseJob,
    ExercisePipeline,
)
from app.modules.notebooks.application.llm import JsonCompletion, NotebookLlm
from app.modules.notebooks.domain.artifacts.handler import (
    ArtifactHandler,
    ProcessContext,
    ProcessedOutput,
)
from app.modules.notebooks.domain.artifacts.kinds.exercise import (
    ExerciseHandler,
    ExerciseOptions,
)
from app.modules.notebooks.domain.artifacts.refs import build_refs_index
from app.modules.notebooks.domain.artifacts.strict import to_strict_schema
from app.modules.notebooks.domain.assessment.blueprint import (
    PLAN_SCHEMA_NAME,
    PLAN_SYSTEM,
    BlueprintRules,
    ItemSpec,
    PlanOut,
    build_blueprint,
    plan_message,
    plan_tokens,
    rules_for,
    swap_template,
)
from app.modules.notebooks.domain.assessment.cost import BATCH_MAX_ITEMS, batch_tokens
from app.modules.notebooks.domain.assessment.exams import exam_for, quotas
from app.modules.notebooks.domain.assessment.items import (
    VERIFY_MAX_TOKENS,
    VERIFY_SCHEMA_NAME,
    VERIFY_SYSTEM,
    VISUAL_BLOCKS,
    CardBatchOut,
    QuizBatchOut,
    VerifyOut,
    batch_task,
    copied_source,
    item_key,
    latex_problem,
    option_letter_problem,
    source_items,
    stimulus_problem,
    unlettered,
    unseen_reference,
    verify_message,
    wants_source_review,
)
from app.modules.notebooks.domain.assessment.modes import choose_mode, mode_spec
from app.modules.notebooks.domain.assessment.profile import (
    PROFILE_MAX_TOKENS,
    PROFILE_SCHEMA_NAME,
    PROFILE_SYSTEM,
    ProfilesOut,
    SourceProfile,
    clean_profiles,
    guess_profile,
    profile_message,
)
from app.modules.notebooks.domain.errors import OutputInvalidError
from app.settings import Settings
from app.shared.ai_tasks import AiTask
from app.shared.openui.blocks import split_blocks
from app.shared.openui.finalize import OpenUiFinalizer
from app.shared.openui.prompt import openui_prompt

import structlog
from pydantic import BaseModel, ValidationError

log = structlog.get_logger(__name__)

BLUEPRINT_KEY: Final = "blueprint"  # in `artifacts.content`
_OPTION_IDS: Final = "abcdefgh"

# One model call: (task, system, messages, schema name, schema, max tokens).
Ask = Callable[
    [AiTask, str, list[dict[str, Any]], str, dict[str, Any], int],
    Awaitable[JsonCompletion],
]


@dataclass(frozen=True, slots=True)
class AssessmentJob:
    """Everything one quiz or card set needs."""

    task: AiTask  # STUDIO_QUIZ or STUDIO_FLASHCARDS
    cards: bool
    handler: ArtifactHandler
    options: BaseModel
    ctx: ProcessContext
    system: str
    context: dict[str, Any]  # the cached sources message
    samples: dict[str, str]  # source label -> its text (for the profile)
    prompt: str | None
    count: int
    types: tuple[str, ...]
    difficulty: str
    mode: str | None  # "auto" or None: chosen here
    wrap: Callable[[str], str] = str  # adds the course context to a batch task


@dataclass(slots=True)
class _Item:
    """A written item with what the checks need."""

    spec: ItemSpec
    data: dict[str, Any]  # the stored question or card
    stem: str
    stimulus: str = ""


@dataclass(slots=True)
class _State:
    accepted: dict[str, _Item] = field(default_factory=dict)  # spec id -> item
    keys: set[str] = field(default_factory=set)
    problems: list[str] = field(default_factory=list)
    rejected: int = 0
    title: str = ""
    pool: list[str] = field(default_factory=list)  # source problems (copy check)


def _chunks(specs: Sequence[ItemSpec], size: int) -> list[list[ItemSpec]]:
    return [list(specs[i : i + size]) for i in range(0, len(specs), size)]


def _shuffled(question: dict[str, Any], seed: str) -> dict[str, Any]:
    """Options in a seeded order with ids a, b, c...; true/false stays."""
    if question.get("type") == "true_false":
        return question
    options = list(question["options"])
    random.Random(seed).shuffle(options)
    new_ids = {o["id"]: _OPTION_IDS[i] for i, o in enumerate(options)}
    order = list(new_ids.values())
    return {
        **question,
        "options": [{"id": new_ids[o["id"]], "text": o["text"]} for o in options],
        "correct": sorted((new_ids[c] for c in question["correct"]), key=order.index),
    }


def _squashed(text: str) -> str:
    """One line of text; a text with a visual block keeps its lines."""
    if "```" in text:
        return text.strip()
    return " ".join(text.split())


def _without_blocks(text: str) -> str:
    """The text with its visual blocks removed (OpenUI off)."""
    if "```" not in text:
        return text
    return "".join(p.text for p in split_blocks(text) if p.kind == "text").strip()


def _copied(stem: str, stimulus: str, pool: Sequence[str]) -> str | None:
    """Why an item copies a source problem or passage, or None."""
    if not pool:
        return None
    if stimulus and (found := copied_source(stimulus, pool)):
        return found
    return copied_source(f"{stimulus} {stem}", pool)


def _split_blocks(text: str) -> tuple[str, list[str]]:
    """The text without its visual blocks, and the blocks as written."""
    if "```" not in text:
        return text, []
    parts = split_blocks(text)
    plain = " ".join(p.text.strip() for p in parts if p.kind == "text").strip()
    return plain, [p.raw.strip() for p in parts if p.kind == "block"]


def _with_stimulus(prompt: str, stimulus: str) -> str:
    """The stimulus as a Markdown quote above the question (a block unquoted)."""
    if not stimulus:
        return prompt
    if "```" in stimulus:
        return f"{stimulus}\n\n{prompt}"
    quoted = "\n".join(f"> {line}" for line in stimulus.splitlines() if line.strip())
    return f"{quoted}\n\n{prompt}"


class AssessmentPipeline:
    """Builds a quiz or card set from a blueprint (see the module docstring)."""

    def __init__(
        self,
        llm: NotebookLlm,
        settings: Settings,
        openui: OpenUiFinalizer | None = None,
    ) -> None:
        """Store the model, the settings and the studio OpenUI finalizer."""
        self.llm = llm
        self.settings = settings
        self.openui = openui if openui is not None and openui.enabled else None
        self.exercises = ExercisePipeline(llm, settings)

    async def run(self, job: AssessmentJob, ask: Ask) -> ProcessedOutput:
        """The finished output with `content.blueprint`.

        Raises:
            OutputInvalidError: No item survived the checks.
        """
        if job.task is AiTask.STUDIO_EXERCISE:
            return await self._exercise(job, ask)
        profiles = await self._profiles(job, ask)
        mode = choose_mode(job.mode, job.prompt, profiles)
        spec = mode_spec(mode, profiles)
        exam = exam_for(mode, job.prompt, profiles)
        rules = rules_for(
            count=job.count,
            types=job.types,
            spec=spec,
            cards=job.cards,
            difficulty=job.difficulty,
            labels=list(job.samples),
            single_template=mode == "question_type_test",
            quotas=quotas(exam, job.count) if exam else (),
        )
        proposed = await self._plan(job, ask, rules, mode, profiles)
        blueprint = build_blueprint(rules, profiles, proposed)
        state = _State()
        if not job.cards and not wants_source_review(job.prompt):
            state.pool = source_items(list(job.samples.values()))
        blueprint = await self._fill(job, ask, rules, blueprint, mode, state)
        if not state.accepted:
            raise OutputInvalidError(state.problems or ["no item passed the checks"])
        return self._output(job, blueprint, profiles, mode, state)

    async def _exercise(self, job: AssessmentJob, ask: Ask) -> ProcessedOutput:
        """An exercise: written and checked section by section."""
        exercise = ExerciseJob(
            task=job.task,
            handler=cast(ExerciseHandler, job.handler),
            options=cast(ExerciseOptions, job.options),
            ctx=job.ctx,
            system=job.system,
            context=job.context,
            prompt=job.prompt,
            wrap=job.wrap,
        )
        output: ProcessedOutput = await self.exercises.run(
            exercise, ask, partial(self._profiles, job, ask)
        )
        return output

    async def _fill(
        self,
        job: AssessmentJob,
        ask: Ask,
        rules: BlueprintRules,
        blueprint: list[ItemSpec],
        mode: str,
        state: _State,
    ) -> list[ItemSpec]:
        """Write every slot; the blueprint as finally written (swapped templates)."""
        pending = blueprint
        rounds = 1 + self.settings.notebooks.assessment_fill_rounds
        size = min(self.settings.notebooks.assessment_batch_size, BATCH_MAX_ITEMS)
        for _ in range(rounds):
            for batch in _chunks(pending, size):
                await self._batch(job, ask, batch, mode, state)
            pending = [s for s in blueprint if s.id not in state.accepted]
            if not pending:
                return blueprint
        if rounds == 1:
            return blueprint
        # Last chance: the failing slots with another template of the same domain.
        swapped = {s.id: swap_template(rules, s) or s for s in pending}
        blueprint = [swapped.get(s.id, s) for s in blueprint]
        for batch in _chunks(list(swapped.values()), size):
            await self._batch(job, ask, batch, mode, state)
        missing = [s.id for s in blueprint if s.id not in state.accepted]
        if missing:
            log.info("notebooks.assessment.shortfall", slots=missing)
        return blueprint

    # - - - Steps - - -

    async def _profiles(self, job: AssessmentJob, ask: Ask) -> list[SourceProfile]:
        if not job.samples:
            return []
        try:
            done = await ask(
                AiTask.STUDIO_SOURCE_PROFILE,
                PROFILE_SYSTEM,
                [{"role": "user", "content": profile_message(job.samples)}],
                PROFILE_SCHEMA_NAME,
                to_strict_schema(ProfilesOut),
                self.llm.max_tokens(AiTask.STUDIO_SOURCE_PROFILE, PROFILE_MAX_TOKENS),
            )
            profiles = clean_profiles(done.data, list(job.samples))
        except (
            OutputInvalidError,
            ValidationError,
        ) as exc:  # best effort, rules take over
            log.info("notebooks.assessment.profile_skipped", error=type(exc).__name__)
            profiles = []
        known = {p.label for p in profiles}
        guessed = [
            guess_profile(label, text)
            for label, text in job.samples.items()
            if label not in known
        ]
        return profiles + guessed

    async def _plan(
        self,
        job: AssessmentJob,
        ask: Ask,
        rules: Any,
        mode: str,
        profiles: list[SourceProfile],
    ) -> list[Any]:
        message = plan_message(rules, mode, profiles, job.prompt)
        try:
            done = await ask(
                AiTask.STUDIO_ASSESSMENT_PLAN,
                PLAN_SYSTEM,
                [job.context, {"role": "user", "content": message}],
                PLAN_SCHEMA_NAME,
                to_strict_schema(PlanOut),
                self.llm.max_tokens(
                    AiTask.STUDIO_ASSESSMENT_PLAN, plan_tokens(job.count)
                ),
            )
            return list(PlanOut.model_validate(done.data).items)
        except (
            OutputInvalidError,
            ValidationError,
        ) as exc:  # best effort, code fills the slots
            log.info("notebooks.assessment.plan_skipped", error=type(exc).__name__)
            return []

    async def _batch(
        self,
        job: AssessmentJob,
        ask: Ask,
        specs: list[ItemSpec],
        mode: str,
        state: _State,
    ) -> None:
        task = batch_task(
            specs,
            mode=mode,
            cards=job.cards,
            prompt=job.prompt,
            avoid=[item.stem for item in state.accepted.values()],
            problems=state.problems[-10:],
            allowed=job.types,
        )
        if self.openui is not None and not job.cards:
            task = f"{task}\n{VISUAL_BLOCKS}\n{openui_prompt('studio')}"
        schema = to_strict_schema(CardBatchOut if job.cards else QuizBatchOut)
        try:
            done = await ask(
                job.task,
                job.system,
                [job.context, {"role": "user", "content": job.wrap(task)}],
                job.handler.schema_name,
                schema,
                self.llm.max_tokens(job.task, batch_tokens(len(specs))),
            )
        except OutputInvalidError as exc:
            state.problems.extend(exc.problems)
            return
        state.title = state.title or str(done.data.get("title") or "")
        items = self._parse(job, specs, done.data, state)
        for item in items:
            await self._blocks(item)
        for item in await self._verified(job, ask, items, state):
            state.accepted[item.spec.id] = item
            state.keys.add(item_key(item.stem, item.stimulus))

    def _parse(
        self,
        job: AssessmentJob,
        specs: list[ItemSpec],
        data: dict[str, Any],
        state: _State,
    ) -> list[_Item]:
        """Rule-checked items; the rejected ones leave their reason in `problems`."""
        key = "cards" if job.cards else "questions"
        raw = data.get(key)
        by_id = {spec.id: spec for spec in specs}
        free = [spec for spec in specs if spec.id not in state.accepted]
        items: list[_Item] = []
        batch_keys: set[str] = set()
        for entry in raw if isinstance(raw, list) else []:
            if not isinstance(entry, dict):
                continue
            spec = by_id.get(str(entry.get("spec_id") or "")) or (
                free[0] if free else None
            )
            if spec is None or spec not in free:
                continue
            item, reason = self._check(
                job, spec, entry, state.keys | batch_keys, state.pool
            )
            if item is None:
                state.rejected += 1
                state.problems.append(f"{spec.id}: {reason}")
                continue
            free.remove(spec)
            batch_keys.add(item_key(item.stem, item.stimulus))
            items.append(item)
        return items

    def _check(
        self,
        job: AssessmentJob,
        spec: ItemSpec,
        entry: dict[str, Any],
        seen: set[str],
        pool: Sequence[str] = (),
    ) -> tuple[_Item | None, str]:
        blocks: list[str] = []
        if not job.cards:
            explanation, blocks = _split_blocks(str(entry.get("explanation") or ""))
            entry = {
                **entry,
                "explanation": unlettered(explanation, entry.get("options") or []),
            }
        stimulus = _squashed(str(entry.get("stimulus") or ""))
        stem = str((entry.get("front") if job.cards else entry.get("prompt")) or "")
        text = stem if not job.cards else f"{stem}\n{entry.get('back') or ''}"
        written = " ".join(
            [text, stimulus, str(entry.get("explanation") or "")]
            + [str(o.get("text") or "") for o in entry.get("options") or []]
        )
        reason = (
            unseen_reference(text, stimulus)
            or stimulus_problem(None if job.cards else spec, stimulus)
            or latex_problem(written)
            or (
                None
                if job.cards
                else option_letter_problem(str(entry.get("explanation") or ""))
            )
            or _copied(stem, stimulus, pool)
            or (
                "duplicate of another item"
                if item_key(stem, stimulus) in seen
                else None
            )
        )
        if reason:
            return None, reason
        processed = self._validated(job, entry)
        if isinstance(processed, str):
            return None, processed
        if blocks:  # the kind collapses whitespace: blocks go back afterwards
            processed["explanation"] = "\n\n".join([processed["explanation"], *blocks])
        return _Item(spec, processed, stem, stimulus), ""

    async def _blocks(self, item: _Item) -> None:
        """Visual blocks of a stimulus or explanation: checked, repaired or dropped."""
        fields = [("explanation", str(item.data.get("explanation") or ""))]
        for name, text in [("stimulus", item.stimulus), *fields]:
            if "```" not in text:
                continue
            if self.openui is None:
                done = _without_blocks(text)
            else:
                done = (await self.openui.finalize(text)).strip()
            if name == "stimulus":
                item.stimulus = done
            else:
                item.data[name] = done

    def _validated(self, job: AssessmentJob, entry: dict[str, Any]) -> Any:
        """The item as the kind stores it, or why the kind rejects it."""
        clean = {k: v for k, v in entry.items() if k not in ("spec_id", "stimulus")}
        for name in ("hint", "topic"):
            clean[name] = clean.get(name) or None
        key = "cards" if job.cards else "questions"
        try:
            out = job.handler.process({"title": "", key: [clean]}, job.options, job.ctx)
        except OutputInvalidError as exc:
            return "; ".join(exc.problems) or "invalid item"
        items = out.content.get(key) or []
        return items[0] if items else "invalid item"

    async def _verified(
        self, job: AssessmentJob, ask: Ask, items: list[_Item], state: _State
    ) -> list[_Item]:
        """The items a solver without sources accepts (all of them if it fails)."""
        if not items or not self.settings.notebooks.assessment_verify:
            return items
        shown = [self._shown(job, item) for item in items]
        try:
            done = await ask(
                AiTask.STUDIO_ITEM_VERIFY,
                VERIFY_SYSTEM,
                [{"role": "user", "content": verify_message(shown, job.cards)}],
                VERIFY_SCHEMA_NAME,
                to_strict_schema(VerifyOut),
                self.llm.max_tokens(AiTask.STUDIO_ITEM_VERIFY, VERIFY_MAX_TOKENS),
            )
            verdicts = {v.id: v for v in VerifyOut.model_validate(done.data).verdicts}
        except (
            OutputInvalidError,
            ValidationError,
        ) as exc:  # best effort, rules already ran
            log.info("notebooks.assessment.verify_skipped", error=type(exc).__name__)
            return items
        kept = []
        for item in items:
            reason = _verdict_problem(job, item, verdicts.get(item.spec.id))
            if reason is None:
                kept.append(item)
            else:
                state.rejected += 1
                state.problems.append(f"{item.spec.id}: {reason}")
        return kept

    def _shown(self, job: AssessmentJob, item: _Item) -> dict[str, object]:
        if job.cards:
            return {"id": item.spec.id, "front": item.data["front"]}
        question = _shuffled(item.data, f"verify:{item.spec.id}")
        item.data = question  # the student sees this order too
        return {
            "id": item.spec.id,
            "type": question["type"],
            "stimulus": item.stimulus,
            "prompt": question["prompt"],
            "options": question["options"],
        }

    # - - - Result - - -

    def _output(
        self,
        job: AssessmentJob,
        blueprint: list[ItemSpec],
        profiles: list[SourceProfile],
        mode: str,
        state: _State,
    ) -> ProcessedOutput:
        ordered = [state.accepted[s.id] for s in blueprint if s.id in state.accepted]
        key = "cards" if job.cards else "questions"
        items = []
        for number, item in enumerate(ordered, start=1):
            data = dict(item.data)
            if job.cards:
                data["id"] = f"c{number}"
            else:
                data = _shuffled(data, f"{job.ctx.seed}:{number}")
                data["id"] = f"q{number}"
                data["prompt"] = _with_stimulus(data["prompt"], item.stimulus)
            items.append(data)
        fallback = "Flash cards" if job.cards else "Quiz"
        title = " ".join(state.title.split()) or fallback
        content = {
            "title": title,
            key: items,
            BLUEPRINT_KEY: {
                "mode": mode,
                "requested": len(blueprint),
                "delivered": len(items),
                "rejected": state.rejected,
                "profiles": [p.as_dict() for p in profiles],
                "items": [s.as_dict() for s in blueprint],
            },
        }
        refs = build_refs_index(
            (item.get("refs") or [] for item in items), job.ctx.pack
        )
        return ProcessedOutput(title=title, content=content, refs_index=refs)


def _verdict_problem(job: AssessmentJob, item: _Item, verdict: Any) -> str | None:
    """Why the solver rejects an item, or None (no verdict: accepted)."""
    if verdict is None:
        return None
    if not verdict.self_contained:
        return f"not self-contained: {verdict.reason[:120]}"
    if not verdict.single_answer:
        return f"ambiguous answer: {verdict.reason[:120]}"
    if job.cards or not verdict.answer:
        return None
    if set(verdict.answer) != set(item.data["correct"]):
        return "a solver without the sources found another key"
    return None
