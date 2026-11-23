"""XP amounts and the level curve (one source of truth for every platform)."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Literal

XpSource = Literal["step", "test", "review", "quest", "exam", "widget"]

STEP_COMPLETED_XP: Final = 20
TEST_SUBMITTED_XP: Final = 10
TEST_SCORE_XP: Final = 20  # scaled by the score share
QUESTION_CORRECT_XP: Final = 10
QUESTION_WRONG_XP: Final = 3
CARD_AGAIN_XP: Final = 3
CARD_RECALLED_XP: Final = 8
DAILY_REVIEW_LIMIT: Final = 20
DAILY_TEST_XP_LIMIT: Final = 100


def xp_to_reach(level: int) -> int:
    """Return the total XP needed to reach a level: 50 * L * (L - 1)."""
    return 50 * level * (level - 1)


@dataclass(frozen=True, slots=True)
class Level:
    """A learner's level and progress inside it."""

    level: int
    xp_into_level: int
    xp_for_next: int


def level_of(xp_total: int) -> Level:
    """Return the level for a total; level 1 starts at 0 XP."""
    level = 1
    while xp_to_reach(level + 1) <= xp_total:
        level += 1
    start = xp_to_reach(level)
    return Level(
        level=level,
        xp_into_level=xp_total - start,
        xp_for_next=xp_to_reach(level + 1) - start,
    )


def attempt_xp(score: Decimal | None, max_score: Decimal) -> int:
    """Return the XP of a submitted test: a flat part plus the score share."""
    share = Decimal(0) if not score or max_score <= 0 else score / max_score
    share = min(max(share, Decimal(0)), Decimal(1))
    return TEST_SUBMITTED_XP + int(round(share * TEST_SCORE_XP))


def best_gain_xp(
    score: Decimal | None,
    max_score: Decimal,
    earlier: list[tuple[Decimal | None, Decimal]],
) -> int:
    """Return the XP of a submitted test: only what beats the block's best so far.

    ``earlier`` are the (score, max_score) of the learner's earlier submitted
    attempts at the same block. The first attempt earns the flat part plus the
    score share; a later one earns only the share above the best earlier one, so
    retaking a test cannot farm XP.
    """
    best = max((attempt_xp(s, m) for s, m in earlier), default=0)
    return max(attempt_xp(score, max_score) - best, 0)


def capped(xp: int, earned_today: int, limit: int) -> int:
    """Return the part of an award that fits under a daily limit."""
    return max(min(xp, limit - earned_today), 0)


def card_xp(rating: int) -> int:
    """Return the XP of one flashcard rating (1 again ... 4 easy)."""
    return CARD_AGAIN_XP if rating <= 1 else CARD_RECALLED_XP


def question_xp(correct: bool) -> int:
    """Return the XP of one review answer."""
    return QUESTION_CORRECT_XP if correct else QUESTION_WRONG_XP
