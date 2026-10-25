"""Assessment modes: what kind of test or card set the student asked for."""

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal

from app.modules.notebooks.domain.assessment.profile import SourceProfile

AssessmentMode = Literal[
    "auto",
    "full_mock",
    "topic_test",
    "question_type_test",
    "vocab_test",
    "formula_recall",
    "concept_check",
    "problem_practice",
    "reading_test",
]
MODES: Final[tuple[str, ...]] = (
    "full_mock",
    "topic_test",
    "question_type_test",
    "vocab_test",
    "formula_recall",
    "concept_check",
    "problem_practice",
    "reading_test",
)


@dataclass(frozen=True, slots=True)
class ModeSpec:
    """Templates of a mode and whether its items carry a stimulus."""

    quiz_templates: tuple[str, ...]
    card_templates: tuple[str, ...]
    needs_stimulus: bool = False
    # In a mixed mode only these templates carry a stimulus (empty: all of them).
    stimulus_templates: frozenset[str] = frozenset()


MODE_SPECS: Final[dict[str, ModeSpec]] = {
    "vocab_test": ModeSpec(
        (
            "sentence_completion",
            "definition_to_word",
            "word_to_definition",
            "synonym",
            "word_in_context",
        ),
        ("term_to_definition", "definition_to_term", "example_sentence"),
    ),
    "formula_recall": ModeSpec(
        ("situation_to_formula", "formula_to_use", "apply_formula", "variables"),
        ("formula_to_name_and_use", "name_to_formula", "worked_example"),
    ),
    "problem_practice": ModeSpec(
        (
            "direct_computation",
            "word_problem",
            "multi_step",
            "conceptual_why",
            "error_spotting",
        ),
        ("problem_to_answer_and_solution", "method_recall", "key_fact"),
    ),
    "reading_test": ModeSpec(
        (
            "main_idea",
            "inference",
            "word_in_context",
            "evidence",
            "purpose_structure",
        ),
        ("term_to_definition", "concept_to_explanation", "key_fact"),
        needs_stimulus=True,
    ),
    "concept_check": ModeSpec(
        (
            "definition",
            "example_identification",
            "compare_contrast",
            "cause_effect",
            "application",
        ),
        ("term_to_definition", "concept_to_explanation", "example", "key_fact"),
    ),
}
# A full mock or a topic test mixes the templates of the sources' own modes.
_KIND_MODE: Final = {
    "vocabulary_list": "vocab_test",
    "problem_set": "problem_practice",
    "formula_sheet": "formula_recall",
    "reading_passages": "reading_test",
    "exam_paper": "full_mock",
}
# Phrases with word boundaries (en, ru, uz). A bare "sinov" (test), "текст" (text),
# "тип" (type) or a word count ("250 words") names no mode on its own.
_APOS: Final = "['‘’ʼ]"
_PROMPT_MODES: Final = (
    (
        "full_mock",
        r"\bmock\b|\bfull (?:test|exam)\b|\bpractice (?:test|exam)\b|"
        r"\bпробн\w*|\bполн\w* (?:тест|экзамен)\w*|"
        rf"\bto{_APOS}liq (?:sinov|test|imtihon)\w*",
    ),
    (
        "vocab_test",
        r"\bvocab\w*|(?<!\d )\bwords?\b|\bсловар\w*|\bлексик\w*|"
        r"\bзначени\w* слов\b|"
        rf"\bso{_APOS}z(?:lar)?(?:ni|ning)? ma{_APOS}no\w*|\blug{_APOS}at\w*",
    ),
    ("formula_recall", r"\bformula\w*|\bформул\w*"),
    (
        "reading_test",
        r"\breading\b|\bpassages?\b|\bчтени\w*|\bпонимани\w* текст\w*|"
        rf"\bo{_APOS}qish\w*|\bmatnni tushun\w*",
    ),
    (
        "question_type_test",
        r"\bonly (?:\w+ ){0,3}questions\b|\b(?:types?|kinds?) of questions?\b|"
        r"\bтолько (?:\w+ ){0,3}вопрос\w*|\bтип\w{0,2} вопрос\w*|"
        r"\bодного типа\b|\bsavol turi\w*|\bfaqat (?:\w+ ){0,3}savol\w*",
    ),
    (
        "problem_practice",
        r"\bproblems?\b|\bexercises?\b|\bзадач\w*|\bупражнени\w*|"
        r"\bmasala\w*|\bmashq\w*",
    ),
)


def _from_prompt(prompt: str) -> str | None:
    text = prompt.casefold()
    for mode, pattern in _PROMPT_MODES:
        if re.search(pattern, text):
            return mode
    return None


def _from_profiles(profiles: Sequence[SourceProfile]) -> str:
    modes = Counter(_KIND_MODE.get(p.kind, "concept_check") for p in profiles)
    if not modes:
        return "concept_check"
    if len(modes) > 1 and "full_mock" not in modes:
        return "topic_test"
    return modes.most_common(1)[0][0]


def choose_mode(
    requested: str | None, prompt: str | None, profiles: Sequence[SourceProfile]
) -> str:
    """The explicit mode, else one read from the prompt, else from the sources."""
    if requested and requested != "auto" and requested in MODES:
        return requested
    return _from_prompt(prompt or "") or _from_profiles(profiles)


def mode_spec(mode: str, profiles: Sequence[SourceProfile]) -> ModeSpec:
    """The templates of a mode; mixed modes take those of the sources' modes."""
    if mode in MODE_SPECS:
        return MODE_SPECS[mode]
    own = [
        MODE_SPECS[m]
        for m in dict.fromkeys(
            _KIND_MODE.get(p.kind, "concept_check") for p in profiles
        )
        if m in MODE_SPECS
    ] or [MODE_SPECS["concept_check"]]
    quiz = tuple(dict.fromkeys(t for spec in own for t in spec.quiz_templates))
    cards = tuple(dict.fromkeys(t for spec in own for t in spec.card_templates))
    passages = frozenset(
        t for spec in own if spec.needs_stimulus for t in spec.quiz_templates
    )
    return ModeSpec(quiz, cards, bool(passages), passages)
