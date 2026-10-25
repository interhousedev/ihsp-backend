"""Points of tests: what an attempt can earn and what a student has earned.

Learners see "12 out of 28 points" per step and per course. A test block is
worth the points of one attempt: all questions, or the best ``pool_size`` ones
when attempts draw a random pool, so a perfect attempt never beats the total.
"""

from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Any

from app.modules.lms.domain.learning.variant import points_of
from app.modules.lms.domain.step_content import (
    H5PBlock,
    InteractiveVideoBlock,
    TestBlock,
)

H5P_POINTS = Decimal(1)


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


def scored_block_max_points(block: H5PBlock | InteractiveVideoBlock) -> Decimal:
    """Return the points of an H5P block (one) or an interactive video (questions)."""
    if isinstance(block, H5PBlock):
        return H5P_POINTS
    return sum_points(
        Decimal(str(i.points)) for i in block.interactions if i.kind == "question"
    )


def scored_earned_points(stored: Mapping[str, Any] | None, total: Decimal) -> Decimal:
    """Return the points a stored H5P or interactive video result has earned."""
    if not stored:
        return Decimal(0)
    if stored.get("kind") == "h5p":
        share = Decimal(str(stored.get("pct", 0))) / 100
        return earned_points(total * share, total)
    return earned_points(Decimal(str(stored.get("score", 0))), total)
