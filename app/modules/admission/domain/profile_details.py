"""Profile details: interests, quiz answers and the completion percent."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from app.modules.admission.domain.errors import InvalidAnswerError, ItemLimitError

INTEREST_FIELDS: Final = (
    "writing",
    "art_design",
    "music_singing",
    "music_instrumental",
    "photography",
    "theater",
    "filmmaking",
    "leadership",
    "public_speaking",
    "advocacy",
    "entrepreneurship",
    "science_research",
    "technology",
    "engineering",
    "aviation",
    "automotive",
    "foreign_languages",
    "foreign_culture",
    "athletics",
)
SERVICE_INTERESTS: Final = (
    "community_service",
    "volunteering",
    "tutoring",
    "environment",
    "healthcare",
    "animal_welfare",
    "child_elder_care",
    "civic_political",
)
QUIZZES: Final = ("career", "algorithm", "budget")
"""`budget` has no questions: its `completed` flag marks the budget step of the
universities flow as reviewed."""
MAX_QUESTIONS: Final = 80
MAX_KEY: Final = 60
MAX_TEXT: Final = 300
MAX_CHOICES: Final = 30

AnswerValue = str | int | bool | list[str]


@dataclass(frozen=True, slots=True)
class Interests:
    """The student's fields of interest and service interests."""

    fields: tuple[str, ...] = ()
    services: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class QuizAnswers:
    """Stored answers of one quiz; multi-choice answers are lists."""

    student_id: UUID
    quiz: str
    answers: Mapping[str, AnswerValue]
    completed: bool = False


def clean_interests(fields: list[str], services: list[str]) -> Interests:
    """Validate against the vocabularies; drop duplicates, keep order."""
    for name, values, allowed in (
        ("interest_fields", fields, INTEREST_FIELDS),
        ("service_interests", services, SERVICE_INTERESTS),
    ):
        for v in values:
            if v not in allowed:
                raise InvalidAnswerError(params={"question": name})
        if len(set(values)) > len(allowed):
            raise ItemLimitError(params={"kind": name, "limit": len(allowed)})
    return Interests(
        tuple(dict.fromkeys(fields)),
        tuple(dict.fromkeys(services)),
    )


def clean_answers(answers: Mapping[str, object]) -> dict[str, AnswerValue]:
    """Validate the shape of quiz answers: small scalars or lists of strings."""
    if len(answers) > MAX_QUESTIONS:
        raise ItemLimitError(params={"kind": "quiz_answers", "limit": MAX_QUESTIONS})
    out: dict[str, AnswerValue] = {}
    for key, value in answers.items():
        if not key or len(key) > MAX_KEY:
            raise InvalidAnswerError(params={"question": key[:MAX_KEY]})
        if isinstance(value, bool | int):
            out[key] = value
        elif isinstance(value, str) and len(value) <= MAX_TEXT:
            out[key] = value
        elif (
            isinstance(value, list)
            and len(value) <= MAX_CHOICES
            and all(isinstance(v, str) and len(v) <= MAX_TEXT for v in value)
        ):
            out[key] = list(dict.fromkeys(value))
        else:
            raise InvalidAnswerError(params={"question": key})
    return out


@dataclass(frozen=True, slots=True)
class Completion:
    """Percent filled and the keys of the details still missing."""

    percent: int
    missing: tuple[str, ...]


def completion(
    *,
    setup_done: bool,
    has_words: bool,
    interests: Interests,
    quizzes_done: frozenset[str],
    has_activity: bool,
) -> Completion:
    """Share of the profile details a student has filled in."""
    checks = (
        ("setup", setup_done),
        ("three_words", has_words),
        ("interest_fields", bool(interests.fields)),
        ("service_interests", bool(interests.services)),
        ("career_quiz", "career" in quizzes_done),
        ("algorithm_quiz", "algorithm" in quizzes_done),
        ("activities", has_activity),
    )
    missing = tuple(k for k, ok in checks if not ok)
    percent = round(100 * (len(checks) - len(missing)) / len(checks))
    return Completion(percent, missing)
