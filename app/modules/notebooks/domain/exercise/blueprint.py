"""The section blueprint of an exercise: passages, their length and the question mix.

The plan is made in code from the options (exam, skill, mode, count), so the model
gets an exact brief: how many sections, how long each passage is, how many questions
of each type. `process()` checks the result against the same blueprint.
"""

from dataclasses import dataclass
from typing import Final, Literal

Exam = Literal["ielts_academic", "sat", "ap", "generic"]
Skill = Literal["reading", "writing", "listening_script", "mixed"]
ExerciseMode = Literal["auto", "full_section", "practice", "drill"]
QuestionKind = Literal[
    "single_choice",
    "multiple_choice",
    "true_false_not_given",
    "matching",
    "gap_fill",
    "short_answer",
    "free_response",
]
OBJECTIVE_KINDS: Final[tuple[str, ...]] = (
    "single_choice",
    "multiple_choice",
    "true_false_not_given",
    "matching",
    "gap_fill",
    "short_answer",
)
MAX_SECTIONS: Final = 12
MAX_QUESTIONS: Final = 60


@dataclass(frozen=True, slots=True)
class EssaySpec:
    """The free response of a section: length, time and the rubric to use."""

    min_words: int
    time_minutes: int
    criteria: tuple[str, ...]  # rubric criteria names (e.g. IELTS TR/CC/LR/GRA)


@dataclass(frozen=True, slots=True)
class SectionSpec:
    """One stimulus and its questions."""

    stimulus: str  # what the stimulus is ("an academic passage", "a task prompt")
    words: tuple[int, int]  # passage length (min, max)
    quotas: tuple[tuple[str, int], ...]  # (question type, count), objective only
    essay: EssaySpec | None = None

    @property
    def question_count(self) -> int:
        """Questions of the section, the essay included."""
        return sum(n for _, n in self.quotas) + (1 if self.essay else 0)


IELTS_WRITING: Final = EssaySpec(
    250,
    40,
    (
        "Task Response (TR)",
        "Coherence and Cohesion (CC)",
        "Lexical Resource (LR)",
        "Grammatical Range and Accuracy (GRA)",
    ),
)
AP_FRQ: Final = EssaySpec(
    300,
    40,
    ("Thesis", "Evidence and Commentary", "Sophistication"),
)
SAT_SHORT: Final = EssaySpec(150, 25, ("Claim", "Use of evidence", "Clarity"))
GENERIC_ESSAY: Final = EssaySpec(
    200, 30, ("Content", "Organisation", "Language", "Accuracy")
)
_ESSAYS: Final[dict[str, EssaySpec]] = {
    "ielts_academic": IELTS_WRITING,
    "ap": AP_FRQ,
    "sat": SAT_SHORT,
    "generic": GENERIC_ESSAY,
}
DEFAULT_COUNTS: Final[dict[str, int]] = {
    "ielts_academic": 13,
    "sat": 10,
    "ap": 8,
    "generic": 10,
}
# The question mix of one reading passage (weights, split over the count).
_READING_MIX: Final[dict[str, tuple[tuple[str, int], ...]]] = {
    "ielts_academic": (
        ("true_false_not_given", 4),
        ("matching", 3),
        ("gap_fill", 4),
        ("single_choice", 2),
    ),
    "ap": (("single_choice", 5), ("multiple_choice", 1), ("short_answer", 2)),
    "generic": (
        ("single_choice", 3),
        ("multiple_choice", 1),
        ("true_false_not_given", 2),
        ("gap_fill", 2),
        ("short_answer", 2),
    ),
}
_LISTENING_MIX: Final = (("gap_fill", 4), ("single_choice", 3), ("matching", 3))
_PASSAGE_WORDS: Final[dict[str, tuple[int, int]]] = {
    "ielts_academic": (700, 900),
    "sat": (25, 150),
    "ap": (400, 650),
    "generic": (350, 600),
}


def _split(mix: tuple[tuple[str, int], ...], count: int) -> tuple[tuple[str, int], ...]:
    """Spread `count` questions over a weighted mix (each type at least one)."""
    kinds = list(mix)[: max(1, count)]
    total = sum(weight for _, weight in kinds)
    shares = [max(1, round(count * weight / total)) for _, weight in kinds]
    while sum(shares) > count:
        shares[shares.index(max(shares))] -= 1
    while sum(shares) < count:
        shares[shares.index(min(shares))] += 1
    return tuple((kind, n) for (kind, _), n in zip(kinds, shares, strict=True) if n)


def _resolved_mode(mode: str, exam: str, count: int) -> str:
    if mode != "auto":
        return mode
    return "full_section" if exam == "ielts_academic" and count >= 26 else "practice"


def _reading(exam: str, mode: str, count: int) -> list[SectionSpec]:
    if exam == "sat":  # SAT RW: one short passage per question
        words = _PASSAGE_WORDS["sat"]
        return [
            SectionSpec(
                "a short passage (SAT Reading and Writing)",
                words,
                (("single_choice", 1),),
            )
            for _ in range(min(count, MAX_SECTIONS))
        ]
    mix = _READING_MIX[exam]
    if mode == "drill":
        mix = mix[:1]
    passages = max(1, min(3, round(count / 13))) if mode == "full_section" else 1
    per = [
        count // passages + (1 if i < count % passages else 0) for i in range(passages)
    ]
    return [
        SectionSpec("an academic reading passage", _PASSAGE_WORDS[exam], _split(mix, n))
        for n in per
    ]


def _writing(exam: str) -> list[SectionSpec]:
    if exam == "sat":  # SAT RW conventions: short texts with one choice each
        return [
            SectionSpec(
                "a short text testing Standard English conventions",
                (25, 120),
                (("single_choice", 1),),
            )
            for _ in range(5)
        ]
    stimulus = (
        "the task prompt (a statement, a debate or the data the student writes about)"
    )
    return [SectionSpec(stimulus, (40, 200), (), _ESSAYS[exam])]


def build_blueprint(exam: str, skill: str, mode: str, count: int) -> list[SectionSpec]:
    """The sections of an exercise; `count` is the number of objective questions."""
    count = max(1, min(count, MAX_QUESTIONS))
    mode = _resolved_mode(mode, exam, count)
    if skill == "writing":
        return _writing(exam)
    if skill == "listening_script":
        mix = _LISTENING_MIX[:1] if mode == "drill" else _LISTENING_MIX
        return [
            SectionSpec(
                "a listening script (a dialogue or a talk the teacher reads aloud, "
                "with speaker names)",
                (450, 700),
                _split(mix, count),
            )
        ]
    sections = _reading(exam, mode, count)
    if skill == "mixed" and exam != "sat":
        sections.append(_writing(exam)[0])
    return sections[:MAX_SECTIONS]


def blueprint_text(sections: list[SectionSpec]) -> str:
    """The blueprint as plain English lines for the task block."""
    lines = []
    for n, spec in enumerate(sections, start=1):
        mix = ", ".join(f"{count} × `{kind}`" for kind, count in spec.quotas)
        essay = (
            f"1 × `free_response` (min_words {spec.essay.min_words}, time_minutes "
            f"{spec.essay.time_minutes}, criteria: {', '.join(spec.essay.criteria)})"
            if spec.essay
            else ""
        )
        questions = "; ".join(part for part in (mix, essay) if part)
        lines.append(
            f"Section {n}: stimulus = {spec.stimulus}, {spec.words[0]} to "
            f"{spec.words[1]} words; questions: {questions}."
        )
    return "\n".join(lines)
