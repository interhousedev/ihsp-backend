"""H5P and interactive video results count as step points and completion."""

from decimal import Decimal
from typing import Any

from app.modules.lms.domain.learning.block_results import passed_block_ids
from app.modules.lms.domain.learning.points import (
    scored_block_max_points,
    scored_earned_points,
)
from app.modules.lms.domain.learning.progress import (
    all_tests_passed,
    completes_on_view,
)
from app.modules.lms.domain.step_content import H5PBlock, InteractiveVideoBlock


def test_points_of_scored_blocks() -> None:
    video = InteractiveVideoBlock(
        id="v",
        interactions=[
            {"id": "a", "at_sec": 1, "points": 2},
            {"id": "b", "at_sec": 2, "kind": "note"},
        ],
    )

    assert scored_block_max_points(H5PBlock(id="h")) == Decimal(1)
    assert scored_block_max_points(video) == Decimal(2)
    assert scored_earned_points({"kind": "h5p", "pct": 50.0}, Decimal(1)) == Decimal(
        "0.5"
    )
    assert scored_earned_points({"score": 5}, Decimal(2)) == Decimal(2)
    assert scored_earned_points(None, Decimal(2)) == Decimal(0)


def test_completion_waits_for_every_gradable_block() -> None:
    cards: dict[str, dict[str, Any]] = {
        "block:h": {"kind": "h5p", "passed": True},
        "block:v": {"kind": "interactive_video", "completed": False},
        "c1": {"due": 1},
    }
    assert passed_block_ids(cards) == {"h"}
    assert not all_tests_passed(["h", "v"], passed_block_ids(cards))
    cards["block:v"]["completed"] = True
    assert all_tests_passed(["h", "v"], passed_block_ids(cards))
    assert not completes_on_view(["h"])
