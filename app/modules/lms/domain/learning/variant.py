"""Attempt variants: which questions a student gets and in which order (LMS-16, 17).

The variant is derived from the attempt id, so it is reproducible, and it is
stored with the attempt, so reloading the page never reshuffles.
"""

import math
import random
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.modules.lms.domain.step_content import Question, TestBlock


@dataclass(frozen=True, slots=True)
class Variant:
    """Question order and option order of one attempt."""

    question_ids: tuple[str, ...]
    option_order: dict[str, list[str]]
    params: dict[str, dict[str, float]] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        """Return the stored form ``{question_ids, option_order, params}``."""
        return {
            "question_ids": list(self.question_ids),
            "option_order": {k: list(v) for k, v in self.option_order.items()},
            "params": {k: dict(v) for k, v in self.params.items()},
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "Variant":
        """Read the stored form."""
        return cls(
            question_ids=tuple(raw.get("question_ids", [])),
            option_order={
                key: list(value) for key, value in raw.get("option_order", {}).items()
            },
            params={
                key: {name: float(num) for name, num in value.items()}
                for key, value in raw.get("params", {}).items()
            },
        )


def build_variant(test: TestBlock, attempt_id: UUID) -> Variant:
    """Pick and order the questions and options for an attempt.

    Questions are all of them or ``pool_size`` random ones, shuffled when
    ``shuffle_questions``. Options are shuffled per question when
    ``shuffle_options``; pinned options keep their original position.
    """
    rng = random.Random(str(attempt_id))
    questions = _pick_questions(test, rng)
    shuffle = test.config.shuffle_options
    option_order = {
        question.id: _option_order(question, rng, shuffle=shuffle)
        for question in questions
        if question.options or question.pairs
    }
    params = {
        question.id: draw_params(question, attempt_id)
        for question in questions
        if question.type == "random_number" and question.random is not None
    }
    return Variant(
        question_ids=tuple(question.id for question in questions),
        option_order=option_order,
        params=params,
    )


def draw_params(question: Question, attempt_id: UUID) -> dict[str, float]:
    """Return the seeded values of the variables of a generated numeric question."""
    spec = question.random
    if spec is None:
        return {}
    rng = random.Random(f"{attempt_id}:{question.id}")
    values: dict[str, float] = {}
    for variable in spec.variables:
        if variable.integer:
            low, high = math.ceil(variable.min), math.floor(variable.max)
            values[variable.name] = float(rng.randint(low, max(low, high)))
        else:
            values[variable.name] = round(rng.uniform(variable.min, variable.max), 2)
    return values


def max_score_of(test: TestBlock, variant: Variant) -> Decimal:
    """Return the total points of the questions in the variant."""
    by_id = {question.id: question for question in test.questions}
    return sum(
        (points_of(by_id[qid]) for qid in variant.question_ids if qid in by_id),
        Decimal(0),
    )


def points_of(question: Question) -> Decimal:
    """Return the points of a question as an exact decimal."""
    return Decimal(str(question.points))


def _pick_questions(test: TestBlock, rng: random.Random) -> list[Question]:
    """Choose the pool and apply the question order."""
    indexes = list(range(len(test.questions)))
    pool = test.config.pool_size
    if pool is not None and 0 < pool < len(indexes):
        indexes = sorted(rng.sample(indexes, pool))
    if test.config.shuffle_questions:
        rng.shuffle(indexes)
    return [test.questions[index] for index in indexes]


def _option_order(
    question: Question, rng: random.Random, *, shuffle: bool
) -> list[str]:
    """Return the option ids (or matching pair ids) of a question in display order."""
    if question.pairs is not None:
        return _shuffled_always([pair.id for pair in question.pairs], rng)
    options = question.options or []
    order = [option.id for option in options]
    if question.type == "sorting":
        return _shuffled_always(order, rng)
    if not shuffle:
        return order
    free = [index for index, option in enumerate(options) if not option.pinned]
    movable = [options[index].id for index in free]
    rng.shuffle(movable)
    for index, option_id in zip(free, movable, strict=True):
        order[index] = option_id
    return order


def _shuffled_always(ids: list[str], rng: random.Random) -> list[str]:
    """Shuffle so that the result differs from the given order when it can."""
    order = list(ids)
    for _ in range(5):
        rng.shuffle(order)
        if order != ids or len(ids) < 2:
            break
    return order
