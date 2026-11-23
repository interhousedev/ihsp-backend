"""Exam sittings (Bluebook-style SAT, AP or custom digital tests).

A sitting lives in the student's step state, in ``StepState.cards`` under
``exam:<block id>`` (card ids never contain ``:``), next to the final result under
``block:<block id>``; no extra table is needed.

Rules:

* Modules are taken one by one; the questions of a module are sent only once it
  starts, and the server keeps its ``started_at`` and ``deadline_at``.
* Answers are accepted until ``deadline_at`` plus ``GRACE``; after that the
  module is closed with what was saved, at its deadline (``late``).
* Adaptive sections (Bluebook "multistage"): with exactly three modules,
  ``modules[0]`` is taken first, then ``modules[1]`` (the harder second module)
  when the first scored at least ``ADAPTIVE_THRESHOLD_PCT`` percent, otherwise
  ``modules[2]`` (the easier one). Adaptive sections of another size, and
  sections that are not adaptive, take every module in order.
* The scaled score of a section is linear between ``scaling.min_score`` and
  ``scaling.max_score`` by the share of points earned in the modules taken. The
  easier path is capped at ``EASY_PATH_CAP`` of the range, as on the digital SAT
  a student routed to the easier module cannot reach the top scores.
* Correct answers and explanations are revealed after the whole exam is finished.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final

from app.modules.lms.domain.learning.answers import normalize_answers
from app.modules.lms.domain.learning.grading import build_review, grade_attempt
from app.modules.lms.domain.learning.variant import Variant, points_of
from app.modules.lms.domain.step_content import (
    ExamBlock,
    ExamModule,
    ExamSection,
    TestBlock,
)

SESSION_PREFIX: Final = "exam:"
GRACE: Final = timedelta(seconds=30)
ADAPTIVE_THRESHOLD_PCT: Final = Decimal(60)
EASY_PATH_CAP: Final = Decimal("0.75")


def session_key(block_id: str) -> str:
    """Return the ``cards`` key of the sitting of an exam block."""
    return f"{SESSION_PREFIX}{block_id}"


@dataclass(slots=True)
class ModuleRun:
    """One module of a sitting: its timing, the saved answers and its score."""

    section_id: str
    module_id: str
    started_at: datetime
    deadline_at: datetime
    answers: dict[str, dict[str, Any]]
    submitted_at: datetime | None = None
    late: bool = False
    score: Decimal = Decimal(0)
    max_score: Decimal = Decimal(0)

    @property
    def is_open(self) -> bool:
        """Return True while the module takes answers."""
        return self.submitted_at is None

    def to_json(self) -> dict[str, Any]:
        """Return the stored form."""
        return {
            "section_id": self.section_id,
            "module_id": self.module_id,
            "started_at": self.started_at.isoformat(),
            "deadline_at": self.deadline_at.isoformat(),
            "answers": self.answers,
            "submitted_at": _iso(self.submitted_at),
            "late": self.late,
            "score": str(self.score),
            "max_score": str(self.max_score),
        }

    @classmethod
    def from_json(cls, raw: Mapping[str, Any]) -> "ModuleRun":
        """Read the stored form."""
        return cls(
            section_id=str(raw["section_id"]),
            module_id=str(raw["module_id"]),
            started_at=datetime.fromisoformat(raw["started_at"]),
            deadline_at=datetime.fromisoformat(raw["deadline_at"]),
            answers={k: dict(v) for k, v in (raw.get("answers") or {}).items()},
            submitted_at=_parse(raw.get("submitted_at")),
            late=bool(raw.get("late")),
            score=Decimal(str(raw.get("score", "0"))),
            max_score=Decimal(str(raw.get("max_score", "0"))),
        )


@dataclass(slots=True)
class ExamSitting:
    """A student's sitting of an exam block, bound to one revision."""

    revision_id: str
    started_at: datetime
    runs: list[ModuleRun]
    finished_at: datetime | None = None

    @property
    def current(self) -> ModuleRun | None:
        """Return the open module, if any."""
        return next((run for run in self.runs if run.is_open), None)

    def to_json(self) -> dict[str, Any]:
        """Return the stored form."""
        return {
            "kind": "exam_session",
            "revision_id": self.revision_id,
            "started_at": self.started_at.isoformat(),
            "finished_at": _iso(self.finished_at),
            "runs": [run.to_json() for run in self.runs],
        }

    @classmethod
    def from_json(cls, raw: Mapping[str, Any]) -> "ExamSitting":
        """Read the stored form."""
        return cls(
            revision_id=str(raw["revision_id"]),
            started_at=datetime.fromisoformat(raw["started_at"]),
            finished_at=_parse(raw.get("finished_at")),
            runs=[ModuleRun.from_json(item) for item in raw.get("runs") or []],
        )


@dataclass(frozen=True, slots=True)
class SectionScore:
    """The raw and scaled score of one section of a finished sitting."""

    section_id: str
    score: Decimal
    max_score: Decimal
    scaled: int | None


# - - - Order of modules - - -


def next_module(
    block: ExamBlock, runs: Sequence[ModuleRun]
) -> tuple[ExamSection, ExamModule] | None:
    """Return the module to take after ``runs``, or None when the exam is over."""
    taken = {run.module_id for run in runs}
    for section in block.sections:
        for module in section_path(section, runs):
            if module.id not in taken:
                return section, module
    return None


def section_path(section: ExamSection, runs: Sequence[ModuleRun]) -> list[ExamModule]:
    """Return the modules of a section a student takes, as far as known yet.

    In an adaptive section of three modules the second one depends on the score of
    the first; until the first is submitted only it is known.
    """
    modules = list(section.modules)
    if not (section.adaptive and len(modules) == 3):
        return modules
    first = next((r for r in runs if r.module_id == modules[0].id), None)
    if first is None or first.is_open:
        return modules[:1]
    harder = pct(first.score, first.max_score) >= ADAPTIVE_THRESHOLD_PCT
    return [modules[0], modules[1] if harder else modules[2]]


def find_module(block: ExamBlock, module_id: str) -> tuple[ExamSection, ExamModule]:
    """Return the section and the module with this id.

    Raises:
        KeyError: The exam has no such module (the revision is pinned, so only a
            corrupted sitting gets here).
    """
    for section in block.sections:
        for module in section.modules:
            if module.id == module_id:
                return section, module
    raise KeyError(module_id)


# - - - Timing - - -


def start_run(section: ExamSection, module: ExamModule, now: datetime) -> ModuleRun:
    """Open a module now, with its server-side deadline."""
    return ModuleRun(
        section_id=section.id,
        module_id=module.id,
        started_at=now,
        deadline_at=now + timedelta(seconds=module.time_limit_sec),
        answers={},
    )


def accepts_answers(run: ModuleRun, now: datetime) -> bool:
    """Return True while the module is open and its deadline plus grace not over."""
    return run.is_open and now <= run.deadline_at + GRACE


def close_run(run: ModuleRun, module: ExamModule, at: datetime, *, late: bool) -> None:
    """Close a module at ``at`` and grade its saved answers."""
    grade = grade_attempt(as_test(module), variant_of(module), run.answers)
    run.submitted_at = at
    run.late = late
    run.score = grade.score
    run.max_score = grade.max_score


def close_expired(block: ExamBlock, sitting: ExamSitting, now: datetime) -> bool:
    """Close the open module whose deadline and grace are over; True if closed."""
    run = sitting.current
    if run is None or accepts_answers(run, now):
        return False
    close_run(run, find_module(block, run.module_id)[1], run.deadline_at, late=True)
    return True


# - - - Answers and grading - - -


def as_test(module: ExamModule) -> TestBlock:
    """Return a module as a test block, so test grading and answers apply."""
    return TestBlock(id=module.id, questions=list(module.questions))


def variant_of(module: ExamModule) -> Variant:
    """Return the fixed variant of a module: authored order, no shuffling."""
    return Variant(
        question_ids=tuple(question.id for question in module.questions),
        option_order={},
    )


def normalize_module_answers(
    module: ExamModule, raw: Mapping[str, Mapping[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Validate answers to the questions of one module (AnswerInvalidError)."""
    return normalize_answers(as_test(module), variant_of(module), raw)


def module_review(module: ExamModule, run: ModuleRun) -> list[dict[str, Any]]:
    """Return the correctness, correct answers and explanations of a module."""
    variant = variant_of(module)
    grade = grade_attempt(as_test(module), variant, run.answers)
    return build_review(as_test(module), variant, grade.correct)


def pct(score: Decimal, max_score: Decimal) -> Decimal:
    """Return the score in percent (100 for a module without points)."""
    return Decimal(100) if max_score <= 0 else score * 100 / max_score


def section_scores(block: ExamBlock, sitting: ExamSitting) -> list[SectionScore]:
    """Return the raw and scaled score of every section of a sitting."""
    scores: list[SectionScore] = []
    for section in block.sections:
        runs = [r for r in sitting.runs if r.section_id == section.id]
        score = sum((r.score for r in runs), Decimal(0))
        top = sum((r.max_score for r in runs), Decimal(0))
        scores.append(
            SectionScore(
                section_id=section.id,
                score=score,
                max_score=top,
                scaled=_scaled(block, section, runs, score, top),
            )
        )
    return scores


def _scaled(
    block: ExamBlock,
    section: ExamSection,
    runs: Sequence[ModuleRun],
    score: Decimal,
    top: Decimal,
) -> int | None:
    """Return the scaled score of a section, or None without a scale."""
    if block.scaling is None:
        return None
    low, high = Decimal(block.scaling.min_score), Decimal(block.scaling.max_score)
    share = pct(score, top) / 100
    easy = (
        section.adaptive
        and len(section.modules) == 3
        and any(r.module_id == section.modules[2].id for r in runs)
    )
    if easy:
        share *= EASY_PATH_CAP
    return int((low + (high - low) * share).to_integral_value())


def exam_max_points(block: ExamBlock) -> Decimal:
    """Return the points of the exam: every module of the harder path."""
    total = Decimal(0)
    for section in block.sections:
        modules = section.modules
        if section.adaptive and len(modules) == 3:
            modules = modules[:2]
        total += sum((points_of(q) for m in modules for q in m.questions), Decimal(0))
    return total


def _iso(value: datetime | None) -> str | None:
    """Return an ISO timestamp or None."""
    return value.isoformat() if value is not None else None


def _parse(value: object) -> datetime | None:
    """Read an ISO timestamp or None."""
    return datetime.fromisoformat(value) if isinstance(value, str) else None
