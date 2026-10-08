"""Points of tests: what an attempt can earn and what a student has earned.

Learners see "12 out of 28 points" per step and per course. A test block is
worth the points of one attempt: all questions, or the best ``pool_size`` ones
when attempts draw a random pool, so a perfect attempt never beats the total.
"""

from collections.abc import Iterable
from decimal import Decimal

from app.modules.lms.domain.learning.variant import points_of
from app.modules.lms.domain.step_content import TestBlock


def block_max_points(block: TestBlock) -> Decimal:
    """Return the points of a perfect attempt at the test block."""
    points = sorted((points_of(question) for question in block.questions), reverse=True)
    pool = block.config.pool_size
    if pool is not None and 0 < pool < len(points):
        points = points[:pool]
    return sum_points(points)


def earned_points(best: Decimal | None, total: Decimal) -> Decimal:
    """Return the best score of a block kept between 0 and the block's points.

    A test can shrink in a later version of the course; the student's earlier
    result then counts up to the new total.
    """
    if best is None or best <= 0:
        return Decimal(0)
    return min(best, total)


def sum_points(values: Iterable[Decimal]) -> Decimal:
    """Return the sum of decimals (``0`` for none)."""
    return sum(values, Decimal(0))
