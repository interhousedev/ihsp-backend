"""Exercises section by section: profile, write, check against the section's stimulus.

1. Profile: the sources are classified like for a quiz (shared with the quiz
   pipeline); the profiles go into every section task.
2. Sections: the kind's blueprint (`ExerciseOptions.blueprint()`) is written one
   section per call (STUDIO_EXERCISE), so a long passage never shares its output
   budget with the next one.
3. Check: the kind's validation, then a cheap solver (STUDIO_ITEM_VERIFY) that sees
   only that section's stimulus and questions; rejected questions are dropped. A
   section that fails or loses more than half of its questions is written again, up
   to `assessment_fill_rounds` more times; the best attempt is kept.
4. The kept sections go through the kind's `process()` once more, which numbers
   the questions and shuffles the choices.
"""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Final

from app.modules.notebooks.application.llm import JsonCompletion, NotebookLlm
from app.modules.notebooks.domain.artifacts.handler import ProcessedOutput
from app.modules.notebooks.domain.artifacts.kind_support import fit_text, norm_key
from app.modules.notebooks.domain.artifacts.kinds.exercise import (
    ESSAY_TOKENS,
    MAX_TOKENS_CAP,
    OVERHEAD_TOKENS,
    PROMPT_CHARS,
    QUESTION_TOKENS,
    TOKENS_PER_WORD,
    ExerciseHandler,
    ExerciseOptions,
)
from app.modules.notebooks.domain.artifacts.strict import to_strict_schema
from app.modules.notebooks.domain.assessment.items import (
    VERIFY_MAX_TOKENS,
    VERIFY_SCHEMA_NAME,
    VERIFY_SYSTEM,
    VerifyOut,
)
from app.modules.notebooks.domain.assessment.profile import SourceProfile
from app.modules.notebooks.domain.errors import OutputInvalidError
from app.modules.notebooks.domain.exercise.blueprint import SectionSpec
from app.settings import Settings
from app.shared.ai_tasks import AiTask

import structlog
from pydantic import ValidationError

log = structlog.get_logger(__name__)

BLUEPRINT_KEY: Final = "blueprint"
KEYED_TYPES: Final = frozenset(
    {"single_choice", "multiple_choice", "true_false_not_given"}
)
UNCHECKED_TYPES: Final = frozenset({"free_response"})

Ask = Callable[
    [AiTask, str, list[dict[str, Any]], str, dict[str, Any], int],
    Awaitable[JsonCompletion],
]
Profiles = Callable[[], Awaitable[list[SourceProfile]]]


@dataclass(frozen=True, slots=True)
class ExerciseJob:
    """What one exercise needs (taken from the quiz pipeline's job)."""

    task: AiTask
    handler: ExerciseHandler
    options: ExerciseOptions
    ctx: Any  # ProcessContext
    system: str
    context: dict[str, Any]
    prompt: str | None
    wrap: Callable[[str], str] = str


@dataclass(slots=True)
class _Section:
    """The best attempt of one section."""

    raw: dict[str, Any] | None = None
    kept: int = 0
    dropped: int = 0
    problems: list[str] = field(default_factory=list)


@dataclass(slots=True)
class _Doc:
    title: str = ""
    instructions: str = ""
    rubric: list[Any] = field(default_factory=list)

    def absorb(self, data: dict[str, Any]) -> None:
        """Keep the first title, instructions and rubric the model wrote."""
        self.title = self.title or str(data.get("title") or "")
        self.instructions = self.instructions or str(data.get("instructions") or "")
        if not self.rubric and isinstance(data.get("rubric"), list):
            self.rubric = list(data["rubric"])


def _profile_lines(profiles: list[SourceProfile]) -> str:
    if not profiles:
        return ""
    lines = "\n".join(
        f"- {p.label}: {p.kind}, {p.subject}; domains: {', '.join(p.domains)}"
        for p in profiles
    )
    return f"\nThe sources are:\n{lines}"


def _section_task(
    job: "ExerciseJob",
    spec: SectionSpec,
    profiles: list[SourceProfile],
    problems: list[str],
) -> str:
    task = job.handler.sections_task(job.options, [spec], job.prompt)
    task += _profile_lines(profiles)
    task += "\nWrite exactly one entry of `sections`."
    if problems:
        task += "\nAn earlier attempt was rejected for: " + "; ".join(problems[-6:])
    return task


def verify_section_message(stimulus: str, questions: list[dict[str, Any]]) -> str:
    """The solver's task: answer each question from this stimulus alone."""
    return (
        "Below is ONE section of an exam exercise: its stimulus and its questions. "
        "Use only this stimulus. For each question decide: self_contained (it can "
        "be answered from this stimulus alone), answer (the option ids you find "
        "correct; for true_false_not_given one of true, false, not_given; for "
        "gap_fill and short_answer the words; [] for matching), single_answer "
        "(exactly one defensible answer) and a short reason.\n\n"
        f"<stimulus>\n{stimulus}\n</stimulus>\n"
        + json.dumps(questions, ensure_ascii=False)
    )


def _shown(question: dict[str, Any]) -> dict[str, Any]:
    shown: dict[str, Any] = {
        "id": question["id"],
        "type": question["type"],
        "prompt": question["prompt"],
    }
    if question["options"]:
        shown["options"] = question["options"]
    if question["items"]:
        shown["items"] = [{"id": i["id"], "text": i["text"]} for i in question["items"]]
    return shown


def _verdict_problem(question: dict[str, Any], verdict: Any) -> str | None:
    """Why the solver rejects a question, or None (no verdict: accepted)."""
    if verdict is None:
        return None
    if not verdict.self_contained:
        return f"not answerable from its stimulus: {verdict.reason[:120]}"
    if not verdict.single_answer:
        return f"ambiguous answer: {verdict.reason[:120]}"
    if question["type"] not in KEYED_TYPES or not verdict.answer:
        return None
    found = {a.strip().lower().replace(" ", "_") for a in verdict.answer}
    if found != {c.lower() for c in question["correct"]}:
        return "a solver with only the stimulus found another key"
    return None


class ExercisePipeline:
    """Writes and checks an exercise section by section (see the module doc)."""

    def __init__(self, llm: NotebookLlm, settings: Settings) -> None:
        """Store the model and the settings."""
        self.llm = llm
        self.settings = settings

    async def run(self, job: ExerciseJob, ask: Ask, profiles: Profiles) -> Any:
        """The finished output with `content.blueprint`.

        Raises:
            OutputInvalidError: No section survived the checks.
        """
        found = await profiles()
        specs = job.options.blueprint()
        doc = _Doc()
        sections = [await self._section(job, ask, spec, found, doc) for spec in specs]
        kept = [s.raw for s in sections if s.raw is not None]
        if not kept:
            problems = [p for s in sections for p in s.problems]
            raise OutputInvalidError(problems[:10] or ["no section passed the checks"])
        data = {
            "title": doc.title,
            "instructions": doc.instructions,
            "rubric": doc.rubric,
            "sections": kept,
        }
        out: ProcessedOutput = job.handler.process(data, job.options, job.ctx)
        out.content[BLUEPRINT_KEY] = {
            "mode": "exercise",
            "sections_requested": len(specs),
            "sections_delivered": len(kept),
            "questions_requested": sum(s.question_count for s in specs),
            "questions_delivered": sum(
                len(s["questions"]) for s in out.content["sections"]
            ),
            # a matching question scores one point per item, like the quota counts
            "points_delivered": out.content["total_points"],
            "rejected": sum(s.dropped for s in sections),
            "profiles": [p.as_dict() for p in found],
        }
        return out

    async def _section(
        self,
        job: ExerciseJob,
        ask: Ask,
        spec: SectionSpec,
        profiles: list[SourceProfile],
        doc: _Doc,
    ) -> _Section:
        best = _Section()
        rounds = 1 + self.settings.notebooks.assessment_fill_rounds
        for _ in range(rounds):
            attempt = await self._attempt(job, ask, spec, profiles, doc, best.problems)
            if attempt.raw is not None and attempt.kept > best.kept:
                best.raw, best.kept = attempt.raw, attempt.kept
            best.dropped += attempt.dropped
            best.problems.extend(attempt.problems)
            if best.kept * 2 >= spec.question_count and best.kept:
                break
        return best

    async def _attempt(
        self,
        job: ExerciseJob,
        ask: Ask,
        spec: SectionSpec,
        profiles: list[SourceProfile],
        doc: _Doc,
        problems: list[str],
    ) -> _Section:
        task = _section_task(job, spec, profiles, problems)
        tokens = section_tokens(spec)
        try:
            done = await ask(
                job.task,
                job.system,
                [job.context, {"role": "user", "content": job.wrap(task)}],
                job.handler.schema_name,
                job.handler.strict_schema(),
                self.llm.max_tokens(job.task, tokens),
            )
        except OutputInvalidError as exc:
            return _Section(problems=list(exc.problems))
        data = done.data
        raw_sections = data.get("sections")
        if not isinstance(raw_sections, list) or not raw_sections:
            return _Section(problems=["no section was written"])
        raw = raw_sections[0]
        doc.absorb(data)
        one = {"title": doc.title, "sections": [raw], "rubric": doc.rubric}
        try:
            checked = job.handler.process(one, job.options, job.ctx)
        except OutputInvalidError as exc:
            return _Section(problems=list(exc.problems))
        section = checked.content["sections"][0]
        rejected = await self._verified(ask, section)
        questions = [
            q
            for q in raw.get("questions") or []
            if isinstance(q, dict)
            and norm_key(fit_text(q.get("prompt"), chars=PROMPT_CHARS)) not in rejected
        ]
        kept = len(section["questions"]) - len(rejected)
        reasons = list(rejected.values())
        if not questions or kept <= 0:
            return _Section(dropped=len(rejected), problems=reasons)
        return _Section(
            raw={**raw, "questions": questions},
            kept=kept,
            dropped=len(rejected),
            problems=reasons,
        )

    async def _verified(self, ask: Ask, section: dict[str, Any]) -> dict[str, str]:
        """Prompt key -> why the solver rejects it (empty when it cannot run)."""
        questions = [
            q for q in section["questions"] if q["type"] not in UNCHECKED_TYPES
        ]
        if not questions or not self.settings.notebooks.assessment_verify:
            return {}
        message = verify_section_message(
            section["stimulus"], [_shown(q) for q in questions]
        )
        try:
            done = await ask(
                AiTask.STUDIO_ITEM_VERIFY,
                VERIFY_SYSTEM,
                [{"role": "user", "content": message}],
                VERIFY_SCHEMA_NAME,
                to_strict_schema(VerifyOut),
                self.llm.max_tokens(AiTask.STUDIO_ITEM_VERIFY, VERIFY_MAX_TOKENS),
            )
            verdicts = {v.id: v for v in VerifyOut.model_validate(done.data).verdicts}
        except (OutputInvalidError, ValidationError) as exc:  # best effort
            log.info("notebooks.exercise.verify_skipped", error=type(exc).__name__)
            return {}
        rejected: dict[str, str] = {}
        for question in questions:
            reason = _verdict_problem(question, verdicts.get(question["id"]))
            if reason is not None:
                rejected[norm_key(question["prompt"])] = f"{question['id']}: {reason}"
        return rejected


def section_tokens(spec: SectionSpec) -> int:
    """`max_tokens` of one section: its passage, questions and essay."""
    return min(
        OVERHEAD_TOKENS
        + spec.words[1] * TOKENS_PER_WORD
        + sum(n for _, n in spec.quotas) * QUESTION_TOKENS
        + (ESSAY_TOKENS if spec.essay else 0),
        MAX_TOKENS_CAP,
    )
