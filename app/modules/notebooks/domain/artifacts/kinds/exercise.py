"""Exercise: a practice set (IELTS, SAT, AP style) with passages and typed questions.

Content: ``{title, instructions, exam, skill, sections: [{id, title, stimulus,
questions}], rubric, total_points}``. The stimulus is Markdown (an original passage,
a listening script or a task prompt) and may hold an OpenUI block of the Studio
subset. Question types: single_choice, multiple_choice, true_false_not_given,
matching, gap_fill (sentence completion), short_answer and free_response (essay).

The schema has no nullable property: every per-type field is `NOT_NULL` and the model
writes ``[]``, ``""`` or ``0`` when a field does not apply to the type.
"""

import random
import string
from dataclasses import dataclass, field
from typing import Any, Final, Literal, Self

from app.modules.notebooks.domain.artifacts.handler import (
    ArtifactHandler,
    ProcessContext,
    ProcessedOutput,
)
from app.modules.notebooks.domain.artifacts.kind_support import (
    CommonOptions,
    document_title,
    dump_options,
    expect_options,
    fit_text,
    norm_key,
    parse_options,
    require_list,
    validate_numbered,
)
from app.modules.notebooks.domain.artifacts.refs import build_refs_index, valid_refs
from app.modules.notebooks.domain.artifacts.strict import NOT_NULL, to_strict_schema
from app.modules.notebooks.domain.enums import ArtifactKind
from app.modules.notebooks.domain.errors import OutputInvalidError
from app.modules.notebooks.domain.exercise.answers import (
    copied_run,
    in_text,
    within_limit,
    word_count,
)
from app.modules.notebooks.domain.exercise.blueprint import (
    DEFAULT_COUNTS,
    MAX_QUESTIONS,
    Exam,
    ExerciseMode,
    QuestionKind,
    SectionSpec,
    Skill,
    blueprint_text,
    build_blueprint,
)
from app.modules.notebooks.domain.limits import ARTIFACT_TITLE_MAX_CHARS
from app.modules.notebooks.domain.prompts.common import difficulty_clause, focus_clause
from app.shared.openui.blocks import split_blocks
from app.shared.openui.validate import validate_block

from pydantic import BaseModel, Field, field_validator, model_validator

Level = Literal["easy", "medium", "hard"]
TFNG_IDS: Final = ("true", "false", "not_given")
TFNG_TEXTS: Final = {"true": "True", "false": "False", "not_given": "Not Given"}
STIMULUS_CHARS: Final = 12_000
PROMPT_CHARS: Final = 1_200
OPTION_CHARS: Final = 300
EXPLANATION_WORDS: Final = 80
INSTRUCTIONS_CHARS: Final = 800
ANSWER_CHARS: Final = 120
MAX_ACCEPTED: Final = 6
MAX_CRITERIA: Final = 6
MAX_BANDS: Final = 10
DESCRIPTOR_CHARS: Final = 400
OUTLINE_ITEMS: Final = 8
# Output tokens: a passage word is about 2 tokens in Russian or Uzbek.
TOKENS_PER_WORD: Final = 2
QUESTION_TOKENS: Final = 300
ESSAY_TOKENS: Final = 1_500
OVERHEAD_TOKENS: Final = 800
MAX_TOKENS_CAP: Final = 32_000
_LETTERS: Final = string.ascii_uppercase


class ExerciseOptions(CommonOptions):
    """Options of an exercise; `count` is the number of objective questions."""

    exam: Exam = "generic"
    skill: Skill = "reading"
    difficulty: Level = "medium"
    count: int | None = Field(default=None, ge=1, le=MAX_QUESTIONS)
    mode: ExerciseMode = "auto"
    target_count: int = 0  # resolved from `count` or the exam's default

    @model_validator(mode="after")
    def _resolve_target_count(self) -> Self:
        self.target_count = self.count or DEFAULT_COUNTS[self.exam]
        return self

    def blueprint(self) -> list[SectionSpec]:
        """The section plan of these options."""
        return build_blueprint(self.exam, self.skill, self.mode, self.target_count)


class OptionOut(BaseModel):
    """A choice option or a matching option (e.g. a heading)."""

    id: str
    text: str


class MatchItemOut(BaseModel):
    """A matching item (e.g. a paragraph) and the id of its option."""

    id: str
    text: str
    answer: str


class BandOut(BaseModel):
    """One band of a criterion and what it looks like."""

    band: str
    descriptor: str


class CriterionOut(BaseModel):
    """A rubric criterion with its band descriptors."""

    name: str
    description: str
    bands: list[BandOut]


def _empty() -> Any:
    return Field(default=None, json_schema_extra=NOT_NULL)


class QuestionOut(BaseModel):
    """A question as the model writes it; fields of other types are empty."""

    id: str | None = _empty()
    type: QuestionKind
    prompt: str
    options: list[OptionOut] | None = _empty()
    correct: list[str] | None = _empty()
    items: list[MatchItemOut] | None = _empty()
    accepted: list[str] | None = _empty()
    word_limit: int | None = _empty()
    min_words: int | None = _empty()
    time_minutes: int | None = _empty()
    criteria: list[CriterionOut] | None = _empty()
    model_outline: list[str] | None = _empty()
    explanation: str | None = _empty()
    refs: list[str] | None = _empty()

    @field_validator("type", mode="before")
    @classmethod
    def _aliases(cls, value: Any) -> Any:
        return {"sentence_completion": "gap_fill", "essay": "free_response"}.get(
            value, value
        )


class SectionOut(BaseModel):
    """A stimulus and its questions."""

    title: str | None = _empty()
    stimulus: str
    questions: list[QuestionOut]


class ExerciseOut(BaseModel):
    """The model's JSON document."""

    title: str
    instructions: str | None = _empty()
    sections: list[SectionOut]
    rubric: list[CriterionOut] | None = _empty()


@dataclass(slots=True)
class _Built:
    """A checked question before numbering and option shuffling."""

    type: str
    data: dict[str, Any]
    refs: list[str] = field(default_factory=list)


def clean_stimulus(text: str) -> str:
    """Markdown with normalised line ends; invalid OpenUI blocks are dropped."""
    flat = text.replace("\r\n", "\n").strip()
    kept: list[str] = []
    for part in split_blocks(flat):
        if part.kind == "text":
            kept.append(part.text)
        elif part.kind == "block" and not validate_block(part.text, "studio"):
            kept.append(part.raw)
    out = "".join(kept).strip()
    return out[:STIMULUS_CHARS]


def _options(
    raw: list[OptionOut] | None, low: int, high: int
) -> list[tuple[str, str]] | None:
    options = [
        (fit_text(o.id, chars=20), fit_text(o.text, chars=OPTION_CHARS))
        for o in raw or []
    ]
    ids = [i for i, _ in options]
    keys = [norm_key(t) for _, t in options]
    if not low <= len(options) <= high or len(set(ids)) != len(ids):
        return None
    if not all(ids) or not all(keys) or len(set(keys)) != len(keys):
        return None
    return options


def _choice(q: QuestionOut, multiple: bool) -> dict[str, Any] | str:
    options = _options(q.options, 3, 6)
    if options is None:
        return "need 3 to 6 options with unique ids and distinct texts"
    ids = {i for i, _ in options}
    correct = list(dict.fromkeys(q.correct or []))
    if not correct or not set(correct) <= ids:
        return "`correct` must list option ids"
    if not multiple and len(correct) != 1:
        return "single_choice has exactly one correct option"
    if multiple and not 2 <= len(correct) < len(options):
        return "multiple_choice has 2 or more correct options, not all"
    return {"options": options, "correct": correct}


def _tfng(q: QuestionOut) -> dict[str, Any] | str:
    answer = {c.strip().lower().replace(" ", "_") for c in q.correct or []}
    if len(answer) != 1 or not answer <= set(TFNG_IDS):
        return "true_false_not_given needs one of true, false, not_given"
    options = [(i, TFNG_TEXTS[i]) for i in TFNG_IDS]
    return {"options": options, "correct": sorted(answer)}


def _matching(q: QuestionOut) -> dict[str, Any] | str:
    options = _options(q.options, 2, 12)
    if options is None:
        return "matching needs 2 to 12 options with unique ids and distinct texts"
    ids = {i for i, _ in options}
    items = [
        (fit_text(i.id, chars=20), fit_text(i.text, chars=OPTION_CHARS), i.answer)
        for i in q.items or []
    ]
    if not 2 <= len(items) <= 10 or len({i for i, _, _ in items}) != len(items):
        return "matching needs 2 to 10 items with unique ids"
    if any(not text or answer not in ids for _, text, answer in items):
        return "every matching item needs a text and an option id as `answer`"
    return {"options": options, "items": items}


def _text_answer(
    q: QuestionOut, stimulus: str, from_text: bool
) -> dict[str, Any] | str:
    limit = max(0, min(int(q.word_limit or 0), 10))
    accepted = list(
        dict.fromkeys(
            a for a in (fit_text(x, chars=ANSWER_CHARS) for x in q.accepted or []) if a
        )
    )[:MAX_ACCEPTED]
    if not accepted:
        return "`accepted` lists at least one answer"
    if not all(within_limit(a, limit) for a in accepted):
        return f"every accepted answer respects the word limit ({limit})"
    if from_text and not in_text(accepted[0], stimulus):
        return "the first accepted answer must be words taken from the passage"
    return {"accepted": accepted, "word_limit": limit}


def _criteria(raw: list[CriterionOut] | None) -> list[dict[str, Any]]:
    out = []
    for item in (raw or [])[:MAX_CRITERIA]:
        name = fit_text(item.name, chars=80)
        bands = [
            {
                "band": fit_text(b.band, chars=20),
                "descriptor": fit_text(b.descriptor, chars=DESCRIPTOR_CHARS),
            }
            for b in item.bands[:MAX_BANDS]
            if fit_text(b.band, chars=20) and fit_text(b.descriptor, chars=10)
        ]
        if name and bands:
            out.append(
                {
                    "name": name,
                    "description": fit_text(item.description, chars=DESCRIPTOR_CHARS),
                    "bands": bands,
                }
            )
    return out


def _essay(
    q: QuestionOut, rubric: list[dict[str, Any]], spec: SectionSpec | None
) -> dict[str, Any] | str:
    criteria = _criteria(q.criteria) or rubric
    if not criteria:
        return "free_response needs rubric `criteria` with band descriptors"
    essay = spec.essay if spec else None
    min_words = int(q.min_words or 0) or (essay.min_words if essay else 150)
    minutes = int(q.time_minutes or 0) or (essay.time_minutes if essay else 30)
    outline = [o for o in (fit_text(x, chars=300) for x in q.model_outline or []) if o][
        :OUTLINE_ITEMS
    ]
    return {
        "min_words": max(20, min(min_words, 1_000)),
        "time_minutes": max(5, min(minutes, 120)),
        "criteria": criteria,
        "model_outline": outline,
    }


def _check(
    q: QuestionOut,
    stimulus: str,
    opts: ExerciseOptions,
    rubric: list[dict[str, Any]],
    spec: SectionSpec | None,
) -> dict[str, Any] | str:
    """The type-specific fields of a valid question, or why it is rejected."""
    from_text = opts.skill in ("reading", "listening_script")
    match q.type:
        case "single_choice":
            return _choice(q, multiple=False)
        case "multiple_choice":
            return _choice(q, multiple=True)
        case "true_false_not_given":
            return _tfng(q)
        case "matching":
            return _matching(q)
        case "gap_fill":
            return _text_answer(q, stimulus, from_text)
        case "short_answer":
            return _text_answer(q, stimulus, False)
        case _:
            return _essay(q, rubric, spec)


def _section(
    number: int,
    raw: SectionOut,
    opts: ExerciseOptions,
    rubric: list[dict[str, Any]],
    spec: SectionSpec | None,
    sources: list[str],
    problems: list[str],
) -> tuple[str, str, list[_Built]] | None:
    stimulus = clean_stimulus(raw.stimulus or "")
    if word_count(stimulus) < 10 and opts.skill != "writing":
        problems.append(f"section {number}: the stimulus is missing or too short")
        return None
    if opts.skill != "writing" and copied_run(stimulus, sources):
        problems.append(
            f"section {number}: the passage copies the sources word for word; "
            "write an original passage in your own words"
        )
        return None
    built: list[_Built] = []
    seen: set[str] = set()
    for index, q in enumerate(raw.questions, start=1):
        prompt = fit_text(q.prompt, chars=PROMPT_CHARS)
        checked = _check(q, stimulus, opts, rubric, spec)
        if not prompt or norm_key(prompt) in seen:
            checked = "a prompt is required and must not repeat"
        if isinstance(checked, str):
            problems.append(f"section {number}, question {index}: {checked}")
            continue
        seen.add(norm_key(prompt))
        explanation = fit_text(q.explanation, words=EXPLANATION_WORDS)
        built.append(
            _Built(
                q.type,
                {"prompt": prompt, "explanation": explanation, **checked},
                list(q.refs or []),
            )
        )
    if not built:
        return None
    title = fit_text(raw.title, chars=120)
    return title, stimulus, built


def _finalise(b: _Built, number: int, seed: int) -> dict[str, Any]:
    """Number the question, shuffle choice options and rename option ids."""
    data = dict(b.data)
    options: list[tuple[str, str]] = list(data.pop("options", []))
    items = data.pop("items", [])
    if b.type in ("single_choice", "multiple_choice"):
        random.Random(f"{seed}:{number}").shuffle(options)
    renamed = {
        old: (old if b.type == "true_false_not_given" else _LETTERS[i])
        for i, (old, _) in enumerate(options)
    }
    order = list(renamed.values())
    correct = sorted((renamed[c] for c in data.pop("correct", [])), key=order.index)
    points = (
        len(items) if b.type == "matching" else 0 if b.type == "free_response" else 1
    )
    return {
        "id": f"q{number}",
        "number": number,
        "type": b.type,
        "prompt": data["prompt"],
        "options": [{"id": renamed[old], "text": text} for old, text in options],
        "correct": correct,
        "items": [
            {"id": f"{number}.{i}", "text": text, "answer": renamed[answer]}
            for i, (_, text, answer) in enumerate(items, start=1)
        ],
        "accepted": data.get("accepted", []),
        "word_limit": data.get("word_limit", 0),
        "min_words": data.get("min_words", 0),
        "time_minutes": data.get("time_minutes", 0),
        "criteria": data.get("criteria", []),
        "model_outline": data.get("model_outline", []),
        "explanation": data["explanation"],
        "points": points,
        "refs": b.refs,
    }


class ExerciseHandler:
    """Options, prompt, schema and validation of the exercise kind."""

    kind: ArtifactKind = ArtifactKind.EXERCISE
    schema_name: str = "nb_exercise"

    def parse_options(self, raw: dict[str, Any]) -> BaseModel:
        """Validate the request's options."""
        return parse_options(ExerciseOptions, raw)

    def stored_options(self, options: BaseModel) -> dict[str, Any]:
        """Options with defaults filled."""
        return dump_options(expect_options(options, ExerciseOptions))

    def report_format(self, options: BaseModel) -> str | None:
        """An exercise has no report format."""
        return None

    def max_tokens(self, options: BaseModel) -> int:
        """Passages, questions and essays of the blueprint, capped."""
        sections = expect_options(options, ExerciseOptions).blueprint()
        total = OVERHEAD_TOKENS
        for spec in sections:
            total += spec.words[1] * TOKENS_PER_WORD
            total += sum(n for _, n in spec.quotas) * QUESTION_TOKENS
            total += ESSAY_TOKENS if spec.essay else 0
        return min(total, MAX_TOKENS_CAP)

    def input_cap_tokens(self, studio_context_tokens: int) -> int:
        """The Studio context cap."""
        return studio_context_tokens

    def strict_schema(self) -> dict[str, Any]:
        """The strict schema of `ExerciseOut`."""
        return to_strict_schema(ExerciseOut)

    def task_block(self, options: BaseModel, prompt: str | None) -> str:
        """The English task text: the blueprint and the rules of every type."""
        opts = expect_options(options, ExerciseOptions)
        return self.sections_task(opts, opts.blueprint(), prompt)

    def sections_task(
        self, options: BaseModel, sections: list[SectionSpec], prompt: str | None
    ) -> str:
        """The task of some sections of the blueprint (one batch of the pipeline)."""
        opts = expect_options(options, ExerciseOptions)
        plan = blueprint_text(sections)
        return (
            f"Create a practice exercise in the style of `{opts.exam}`, skill "
            f"`{opts.skill}`. {difficulty_clause(opts.difficulty)} Follow this "
            f"blueprint exactly, one entry of `sections` per line:\n{plan}\n"
            "First decide what the sources are about, then write each stimulus. A "
            "passage or script is ORIGINAL: write it in your own words from the "
            "ideas of the sources (adapt, summarise, re-tell); never copy sentences "
            "from them. Every question must be answerable from its own stimulus "
            "alone. Types and their fields (leave the fields of other types empty: "
            '[] or "" or 0): `single_choice` = 4 `options`, one id in `correct`; '
            "`multiple_choice` = 5 `options`, 2 or 3 ids in `correct`; "
            '`true_false_not_given` = `correct` is ["true"], ["false"] or '
            '["not_given"] (not_given = the passage does not say), no options; '
            "`matching` = `options` (e.g. headings, with more options than items) "
            "and `items` (e.g. paragraphs A-F) whose `answer` is an option id; "
            "`gap_fill` = a sentence with ____ for the gap, `accepted` answers "
            "(the first one copied exactly from the stimulus, then variants), "
            "`word_limit` (e.g. 2 for NO MORE THAN TWO WORDS); `short_answer` = "
            "`accepted` answers and `word_limit`; `free_response` = the task in "
            "`prompt`, `min_words`, `time_minutes`, `criteria` (each with band "
            "descriptors, e.g. IELTS bands 9, 7, 5) and a `model_outline` (the "
            "points of a strong answer, not a full essay). Number the matching items "
            "and paragraphs in the stimulus the same way. `explanation` (at most "
            f"{EXPLANATION_WORDS} words) shows where in the stimulus the answer is. "
            "`instructions` tells the student what to do and how long it takes. "
            "`rubric` is the overall rubric of a writing task, else []. A stimulus "
            "may contain one ```openui block of the Studio catalogue (a table or a "
            "chart for IELTS Writing Task 1), nothing else."
            f"{focus_clause(prompt)}"
        )

    def default_title(self, notebook_title: str, options: BaseModel) -> str:
        """``Exercise: <notebook>``."""
        return f"Exercise: {notebook_title}"[:ARTIFACT_TITLE_MAX_CHARS]

    def process(
        self, data: dict[str, Any], options: BaseModel, ctx: ProcessContext
    ) -> ProcessedOutput:
        """Check every section and question, number them and shuffle choices."""
        opts = expect_options(options, ExerciseOptions)
        problems: list[str] = []
        raw_rubric = data.get("rubric")
        listed: list[Any] = raw_rubric if isinstance(raw_rubric, list) else []
        rubric = _criteria(
            [r for _, r in validate_numbered(CriterionOut, listed, [], "criterion")]
        )
        specs = opts.blueprint()
        # Whole sources, so a copied run across two passages is found too.
        sources = [" ".join(p.text for p in s.passages) for s in ctx.pack.sources]
        sections_out: list[dict[str, Any]] = []
        number = 0
        raw_sections = validate_numbered(
            SectionOut, require_list(data, "sections"), problems, "section"
        )
        for index, raw in raw_sections:
            spec = specs[index - 1] if index - 1 < len(specs) else None
            built = _section(index, raw, opts, rubric, spec, sources, problems)
            if built is None:
                continue
            title, stimulus, drafts = built
            stored = []
            for b in drafts:
                if number >= MAX_QUESTIONS:
                    break
                number += 1
                b.refs = valid_refs(b.refs, ctx.pack)
                stored.append(_finalise(b, number, ctx.seed))
            sections_out.append(
                {
                    "id": f"s{len(sections_out) + 1}",
                    "title": title,
                    "stimulus": stimulus,
                    "questions": stored,
                }
            )
        if not sections_out:
            raise OutputInvalidError(problems or ["no valid sections"])
        questions = [q for s in sections_out for q in s["questions"]]
        title = document_title(data, ctx.pack, "Exercise")
        content = {
            "title": title,
            "instructions": fit_text(
                data.get("instructions"), chars=INSTRUCTIONS_CHARS
            ),
            "exam": opts.exam,
            "skill": opts.skill,
            "sections": sections_out,
            "rubric": rubric or None,
            "total_points": sum(q["points"] for q in questions),
        }
        return ProcessedOutput(
            title=title,
            content=content,
            refs_index=build_refs_index((q["refs"] for q in questions), ctx.pack),
        )


HANDLER: ArtifactHandler = ExerciseHandler()
