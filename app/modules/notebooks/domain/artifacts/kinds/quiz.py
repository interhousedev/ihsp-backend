"""Quiz (§ 3.4.4): single, multiple and true/false questions with explanations."""

import random
import re
import string
from dataclasses import dataclass
from typing import Any, Final, Literal

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
from app.modules.notebooks.domain.artifacts.refs import (
    build_refs_index,
    cites_honestly,
    keep_items_with_refs,
    valid_refs,
)
from app.modules.notebooks.domain.artifacts.strict import to_strict_schema
from app.modules.notebooks.domain.enums import ArtifactKind
from app.modules.notebooks.domain.errors import OutputInvalidError
from app.modules.notebooks.domain.limits import ARTIFACT_TITLE_MAX_CHARS
from app.modules.notebooks.domain.prompts.common import difficulty_clause, focus_clause

from pydantic import BaseModel, Field, field_validator

QuestionType = Literal["single", "multiple", "true_false"]
Level = Literal["easy", "medium", "hard"]
Count = Literal["fewer", "standard", "more"]

QUESTION_COUNTS: Final = {"fewer": 5, "standard": 10, "more": 20}
# About 700 tokens per question in Russian or Uzbek (prompt, 4 options, explanation
# and hint), plus the title.
MAX_TOKENS: Final = {"fewer": 4_000, "standard": 7_500, "more": 14_000}
MIN_OPTIONS: Final = 2
MAX_OPTIONS: Final = 6
EXPLANATION_WORDS: Final = 60
PROMPT_CHARS: Final = 400
OPTION_CHARS: Final = 200
HINT_CHARS: Final = 200
TOPIC_CHARS: Final = 60
_OPTION_IDS: Final = string.ascii_lowercase
# A filler instead of an answer: "Option D", "Вариант Б", "Variant 3", "Javob A"...
_PLACEHOLDER: Final = re.compile(
    r"^(?:option|variant|answer|choice|вариант|ответ|javob|variant)\s*"
    r"[a-zа-я0-9]?[.)]?$",
    re.IGNORECASE,
)
_TYPE_PHRASES: Final = {
    "single": "single choice with 4 options",
    "multiple": "multiple choice with 4 or 5 options and 2 or 3 correct ones",
    "true_false": "true/false (two options with the ids `true` and `false`)",
}


def _all_types() -> list[QuestionType]:
    return ["single", "multiple", "true_false"]


class QuizOptions(CommonOptions):
    """`QuizOptions` of § 4.4 with the defaults filled."""

    count: Count = "standard"
    difficulty: Level = "medium"
    types: list[QuestionType] = Field(default_factory=_all_types, min_length=1)

    @field_validator("types")
    @classmethod
    def _unique_types(cls, value: list[QuestionType]) -> list[QuestionType]:
        return list(dict.fromkeys(value))


class OptionOut(BaseModel):
    """An answer option as the model writes it."""

    id: str
    text: str


class QuestionOut(BaseModel):
    """A question as the model writes it (`QuizQuestion` of § 4.4)."""

    id: str | None = None
    type: QuestionType
    prompt: str
    options: list[OptionOut]
    correct: list[str]
    explanation: str
    hint: str | None = None
    difficulty: Level | None = None
    topic: str | None = None
    refs: list[str] | None = None


class QuizOut(BaseModel):
    """The model's JSON document."""

    title: str
    questions: list[QuestionOut]


@dataclass(slots=True)
class _Draft:
    """A question that passed the rules, before ids, shuffle and refs."""

    type: str
    prompt: str
    options: list[tuple[str, str]]  # (id, text)
    correct: list[str]
    explanation: str
    hint: str | None
    difficulty: str
    topic: str | None
    refs: list[str]  # raw labels first, resolved by `valid_refs` later
    trusted: bool = True  # valid refs, or honestly none (see `cites_honestly`)


def is_placeholder(text: str) -> bool:
    """True for a filler option: "Option D", a Markdown heading, no real words."""
    flat = text.strip()
    return (
        not flat
        or flat.startswith("#")
        or _PLACEHOLDER.fullmatch(flat) is not None
        or not norm_key(flat)
    )


def _clean_options(raw: list[OptionOut]) -> list[tuple[str, str]] | None:
    """Options with unique ids and distinct, real texts, 2 to 6 of them."""
    options = [
        (fit_text(o.id, chars=20), fit_text(o.text, chars=OPTION_CHARS)) for o in raw
    ]
    ids = [option_id for option_id, _ in options]
    if not MIN_OPTIONS <= len(options) <= MAX_OPTIONS or len(set(ids)) != len(ids):
        return None
    if any(not option_id or is_placeholder(text) for option_id, text in options):
        return None
    keys = [norm_key(text) for _, text in options]
    if len(set(keys)) != len(keys):  # two options that say the same thing
        return None
    return options


def _true_false(
    options: list[tuple[str, str]], correct: list[str]
) -> tuple[list[tuple[str, str]], list[str]] | None:
    """Exactly the options `true` and `false` (in this order) and one correct."""
    by_id = {option_id.lower(): text for option_id, text in options}
    if set(by_id) != {"true", "false"} or len(options) != 2:
        return None
    answer = {item.lower() for item in correct}
    if len(answer) != 1 or not answer <= set(by_id):
        return None
    ordered = [(key, by_id[key]) for key in ("true", "false")]
    return ordered, sorted(answer)


def _choice_correct(
    kind: str, options: list[tuple[str, str]], correct: list[str]
) -> list[str] | None:
    """The correct ids of a single or multiple question, or None when invalid."""
    ids = {option_id for option_id, _ in options}
    unique = list(dict.fromkeys(fit_text(item, chars=20) for item in correct))
    if not unique or not set(unique) <= ids:
        return None
    if kind == "single":
        return unique if len(unique) == 1 else None
    return unique if 2 <= len(unique) < len(options) else None


def _checked_answers(
    item: QuestionOut, options: list[tuple[str, str]]
) -> tuple[list[tuple[str, str]], list[str]] | None:
    """Apply the per-type rules of § 3.4.4; None when the question is broken."""
    if item.type == "true_false":
        return _true_false(options, item.correct)
    correct = _choice_correct(item.type, options, item.correct)
    return None if correct is None else (options, correct)


def _rejection(
    item: QuestionOut,
    opts: QuizOptions,
    has_text: bool,
    options: list[tuple[str, str]] | None,
    answers: tuple[list[tuple[str, str]], list[str]] | None,
) -> str | None:
    """Why a question is dropped, or None when it is fine."""
    if item.type not in opts.types:
        return f"type {item.type} was not requested"
    if not has_text:
        return "prompt and explanation are required"
    if options is None:
        return (
            "need 2 to 6 options with unique ids and distinct real texts "
            "(no placeholders such as 'Option D', no headings, no repeats)"
        )
    if answers is None:
        return f"wrong `correct` for type {item.type}"
    return None


def _draft(
    item: QuestionOut, number: int, opts: QuizOptions, problems: list[str]
) -> _Draft | None:
    """Turn one validated question into a draft, or report why it is dropped."""
    prompt = fit_text(item.prompt, chars=PROMPT_CHARS)
    explanation = fit_text(item.explanation, words=EXPLANATION_WORDS)
    options = _clean_options(item.options)
    answers = None if options is None else _checked_answers(item, options)
    reason = _rejection(item, opts, bool(prompt and explanation), options, answers)
    if reason or answers is None:
        problems.append(f"question {number}: {reason or 'invalid'}")
        return None
    return _Draft(
        type=item.type,
        prompt=prompt,
        options=answers[0],
        correct=answers[1],
        explanation=explanation,
        hint=fit_text(item.hint, chars=HINT_CHARS) or None,
        difficulty=item.difficulty or opts.difficulty,
        topic=fit_text(item.topic, chars=TOPIC_CHARS) or None,
        refs=list(item.refs or []),
    )


def _without_duplicates(drafts: list[_Draft]) -> list[_Draft]:
    """Drop questions whose normalised prompt was already seen."""
    seen: set[str] = set()
    unique = []
    for draft in drafts:
        key = norm_key(draft.prompt)
        if key not in seen:
            seen.add(key)
            unique.append(draft)
    return unique


def _finalise(draft: _Draft, number: int, seed: int) -> dict[str, Any]:
    """Shuffle (single and multiple), rewrite ids and build the stored question."""
    options = list(draft.options)
    if draft.type == "true_false":
        new_ids = {option_id: option_id for option_id, _ in options}
    else:
        random.Random(f"{seed}:{number}").shuffle(options)
        new_ids = {old: _OPTION_IDS[i] for i, (old, _) in enumerate(options)}
    correct = sorted(
        (new_ids[old] for old in draft.correct), key=list(new_ids.values()).index
    )
    return {
        "id": f"q{number}",
        "type": draft.type,
        "prompt": draft.prompt,
        "options": [{"id": new_ids[old], "text": text} for old, text in options],
        "correct": correct,
        "explanation": draft.explanation,
        "hint": draft.hint,
        "difficulty": draft.difficulty,
        "topic": draft.topic,
        "refs": draft.refs,
    }


class QuizHandler:
    """Options, prompt, schema and validation of the quiz kind."""

    kind: ArtifactKind = ArtifactKind.QUIZ
    schema_name: str = "nb_quiz"

    def parse_options(self, raw: dict[str, Any]) -> BaseModel:
        """Validate the request's options."""
        return parse_options(QuizOptions, raw)

    def stored_options(self, options: BaseModel) -> dict[str, Any]:
        """Options with defaults filled."""
        return dump_options(expect_options(options, QuizOptions))

    def report_format(self, options: BaseModel) -> str | None:
        """A quiz has no report format."""
        return None

    def max_tokens(self, options: BaseModel) -> int:
        """2 500 / 4 500 / 8 000 for fewer / standard / more."""
        return MAX_TOKENS[expect_options(options, QuizOptions).count]

    def input_cap_tokens(self, studio_context_tokens: int) -> int:
        """The Studio context cap."""
        return studio_context_tokens

    def strict_schema(self) -> dict[str, Any]:
        """The strict schema of `QuizOut`."""
        return to_strict_schema(QuizOut)

    def task_block(self, options: BaseModel, prompt: str | None) -> str:
        """The English task text (§ 3.4.4) for the last user message."""
        opts = expect_options(options, QuizOptions)
        return (
            f"Create {QUESTION_COUNTS[opts.count]} quiz questions. "
            f"{_mix_sentence(opts.types)} {difficulty_clause(opts.difficulty)} "
            "Each question tests one idea of the subject (a definition, a rule, a "
            "calculation, an application), never what a heading says or where "
            "something is written. Every option is a real answer: distractors are "
            "plausible, wrong for a clear reason (a typical mistake) and of similar "
            "length to the correct option; never use fillers such as 'Option D', "
            "'all of the above' or 'none of the above'. The options are shuffled "
            "after you answer, so `explanation` and `hint` never refer to an option "
            f"by its letter or position. `explanation` (at most {EXPLANATION_WORDS} "
            "words) says why the correct answer is right and why the most tempting "
            "wrong answer is wrong. `hint` nudges without revealing the answer. "
            "`correct` lists the ids of the right options."
            f"{focus_clause(prompt)}"
        )

    def default_title(self, notebook_title: str, options: BaseModel) -> str:
        """``Quiz: <notebook>``."""
        return f"Quiz: {notebook_title}"[:ARTIFACT_TITLE_MAX_CHARS]

    def process(
        self, data: dict[str, Any], options: BaseModel, ctx: ProcessContext
    ) -> ProcessedOutput:
        """Validate, dedupe, resolve refs, shuffle options and number the questions."""
        opts = expect_options(options, QuizOptions)
        problems: list[str] = []
        items = validate_numbered(
            QuestionOut, require_list(data, "questions"), problems, "question"
        )
        drafts = [
            draft
            for number, item in items
            if (draft := _draft(item, number, opts, problems)) is not None
        ]
        drafts = _without_duplicates(drafts)
        for draft in drafts:
            raw = draft.refs
            draft.refs = valid_refs(raw, ctx.pack)
            draft.trusted = cites_honestly(raw, draft.refs)
        wanted = QUESTION_COUNTS[opts.count]
        kept = keep_items_with_refs(drafts, lambda d: d.trusted, wanted)[:wanted]
        if not kept:
            raise OutputInvalidError(problems or ["no valid questions"])
        questions = [_finalise(d, n, ctx.seed) for n, d in enumerate(kept, start=1)]
        title = document_title(data, ctx.pack, "Quiz")
        index = build_refs_index((q["refs"] for q in questions), ctx.pack)
        return ProcessedOutput(
            title=title,
            content={"title": title, "questions": questions},
            refs_index=index,
        )


def _mix_sentence(types: list[QuestionType]) -> str:
    """Describe the question types to create."""
    if len(types) == len(_TYPE_PHRASES):
        return (
            "Mix: mostly single choice with 4 options, some multiple choice with "
            "4 or 5 options and 2 or 3 correct ones, a few true/false (two options "
            "with the ids `true` and `false`)."
        )
    phrases = ", ".join(f"`{kind}` = {_TYPE_PHRASES[kind]}" for kind in types)
    return f"Use only these question types: {phrases}."


HANDLER: ArtifactHandler = QuizHandler()
