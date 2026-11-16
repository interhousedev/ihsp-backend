"""The activity and honor rubric (§9.2): anchors E..A and the deterministic overall."""

import math
from collections.abc import Mapping
from typing import Final, Literal

Grade = Literal["A", "B", "C", "D", "E"]
Dimension = Literal["clarity", "role_name", "impact", "alignment"]

RUBRIC_VERSION: Final = "items-2026-11-1"
DIMENSIONS: Final[tuple[Dimension, ...]] = (
    "clarity",
    "role_name",
    "impact",
    "alignment",
)
GRADES: Final[tuple[Grade, ...]] = ("E", "D", "C", "B", "A")
POINTS: Final[dict[str, int]] = {g: i + 1 for i, g in enumerate(GRADES)}
WEIGHTS: Final[dict[Dimension, float]] = {
    "impact": 0.35,
    "alignment": 0.25,
    "clarity": 0.20,
    "role_name": 0.20,
}
E_CAP: Final = "D"
"""Any dimension at E caps the overall at D."""

PROJECTED_IMPACT_CAP: Final = "C"
"""Impact argued only from projected numbers never grades above C."""

ANCHORS: Final[dict[str, dict[Dimension, dict[Grade, str]]]] = {
    "activity": {
        "clarity": {
            "A": "Every phrase carries a fact; a reader sees what was done at once.",
            "B": "Clear and concrete with one vague or redundant phrase.",
            "C": "Understandable but generic; several words carry no fact.",
            "D": "Hard to follow; jargon, filler or missing verbs.",
            "E": "Empty, unreadable or unrelated to the activity.",
        },
        "role_name": {
            "A": "A precise role and organization that show responsibility and level.",
            "B": "A clear role; the level or scope is only implied.",
            "C": "A generic role such as member or participant without scope.",
            "D": "The role is unclear or only implied by the description.",
            "E": "No role and no organization.",
        },
        "impact": {
            "A": "Current, specific numbers or outcomes that show scale and change.",
            "B": "A concrete outcome with some scale but few numbers.",
            "C": "Effort is described; the result is vague.",
            "D": "Only duties are listed; no result.",
            "E": "Nothing about what happened because of the student.",
        },
        "alignment": {
            "A": "Clearly carries one or more of the student's three words.",
            "B": "Supports a word, but the link must be inferred.",
            "C": "Neutral to the words.",
            "D": "Pulls against the profile the words describe.",
            "E": "Contradicts the words.",
        },
    },
    "honor": {
        "clarity": {
            "A": "Name, level and year are clear at a glance.",
            "B": "Clear with one ambiguous element.",
            "C": "Understandable but the reader must guess the award's meaning.",
            "D": "Confusing name or missing context.",
            "E": "Empty or unreadable.",
        },
        "role_name": {
            "A": (
                "The exact title and level"
                " (school, regional, national, international)."
            ),
            "B": "A clear title; the level is implied.",
            "C": "A generic title without level.",
            "D": "The title is unclear.",
            "E": "No title.",
        },
        "impact": {
            "A": (
                "Selectivity and scale are stated"
                " (rank, field size, acceptance rate)."
            ),
            "B": "Some selectivity or scale is stated.",
            "C": "The award is named; selectivity is unknown.",
            "D": "Participation only.",
            "E": "Nothing about the distinction.",
        },
        "alignment": {
            "A": "Clearly carries one or more of the student's three words.",
            "B": "Supports a word, but the link must be inferred.",
            "C": "Neutral to the words.",
            "D": "Pulls against the profile the words describe.",
            "E": "Contradicts the words.",
        },
    },
}


def overall_item(grades: Mapping[str, str]) -> Grade:
    """Return the weighted overall grade: rounded half down, any E caps it at D."""
    score = sum(WEIGHTS[d] * POINTS[grades[d]] for d in DIMENSIONS)
    points = max(1, math.ceil(round(score, 6) - 0.5))
    grade = GRADES[min(points, 5) - 1]
    if any(grades[d] == "E" for d in DIMENSIONS) and POINTS[grade] > POINTS[E_CAP]:
        return E_CAP
    return grade


def cap(grade: Grade, ceiling: Grade) -> Grade:
    """Return the lower of two grades."""
    return grade if POINTS[grade] <= POINTS[ceiling] else ceiling


def rubric_text(kind: str) -> str:
    """Return the anchors of an item kind as prompt text."""
    lines: list[str] = []
    for dim in DIMENSIONS:
        lines.append(f"{dim}:")
        for grade in reversed(GRADES):
            lines.append(f"  {grade}: {ANCHORS[kind][dim][grade]}")
    return "\n".join(lines)
