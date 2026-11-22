"""Essay categories of prompts and the short answers kept for short prompts.

The category is derived, never stored: the prompt owner (Common App), keywords of the
prompt text and of the stored group label, then the word limit. The same input always
gives the same category.
"""

import datetime as dt
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal
from uuid import UUID

from app.modules.admission.domain.essay_flow import PromptRef

Category = Literal[
    "personal_statement",
    "why_us",
    "community",
    "academic",
    "activity",
    "short_answer",
    "other",
]
CATEGORIES: Final[tuple[Category, ...]] = (
    "personal_statement",
    "why_us",
    "community",
    "academic",
    "activity",
    "short_answer",
    "other",
)

SHORT_WORDS: Final = 150
"""Prompts with a limit up to this many words are short answers."""
SHORT_CHARS: Final = 1000
"""The same, when the limit is counted in characters."""
SHORT_ANSWER_MAX_WORDS: Final = 150
"""The most words a stored short answer holds."""

_KEYWORDS: Final[tuple[tuple[Category, re.Pattern[str]], ...]] = (
    (
        "why_us",
        re.compile(
            r"why (us|this|our|do you want|are you (interested|applying))"
            r"|why .{0,40}(college|university|school|institute|program)"
            r"|what (attracts|draws|excites) you"
            r"|почему .{0,40}(мы|наш|выбра|хотите)|nega (biz|bizni)",
            re.I,
        ),
    ),
    (
        "community",
        re.compile(r"communit|диаспор|сообществ|jamoa|hamjamiyat", re.I),
    ),
    (
        "activity",
        re.compile(
            r"extracurricular|activit|hobb|volunteer|club\b|внеучеб|занятие|"
            r"увлечени|faoliyat|qiziqish",
            re.I,
        ),
    ),
    (
        "academic",
        re.compile(
            r"academic|intellectual|\bmajor\b|course of study|field of study|"
            r"scholar|research|учеб|академ|интеллект|ilmiy|akademik",
            re.I,
        ),
    ),
)


def classify_prompt(prompt: PromptRef, label: str = "") -> Category:
    """The category of one prompt; `label` is the stored AI name of its group."""
    if prompt.institution_id is None:
        return "personal_statement"
    text = f"{prompt.prompt}\n{label}"
    for category, pattern in _KEYWORDS:
        if pattern.search(text):
            return category
    limit = prompt.word_limit
    if limit is not None:
        cap = SHORT_CHARS if prompt.limit_unit.startswith("char") else SHORT_WORDS
        if limit <= cap:
            return "short_answer"
    return "other"


def is_university_specific(prompt: PromptRef) -> bool:
    """A "Why us" prompt or one naming its own university: never shared."""
    if prompt.institution_id is None:
        return False
    if classify_prompt(prompt) == "why_us":
        return True
    name = prompt.institution_name.strip().lower()
    return len(name) > 2 and name in prompt.prompt.lower()


def classify_group(prompts: Sequence[PromptRef], label: str = "") -> Category:
    """The commonest category among the members; a tie goes to the earlier one."""
    if not prompts:
        return "other"
    votes = Counter(classify_prompt(p, label) for p in prompts)
    top = max(votes.values())
    return next(c for c in CATEGORIES if votes.get(c) == top)


@dataclass(frozen=True, slots=True)
class ShortAnswer:
    """A student's short text for one supplemental prompt; stored sealed."""

    student_id: UUID
    prompt_key: str
    text: str
    word_count: int
    updated_at: dt.datetime | None = None
