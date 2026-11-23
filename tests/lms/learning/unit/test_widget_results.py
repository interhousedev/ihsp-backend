"""Graded code and HTML widgets: best score kept, pass sticky, counted as a point."""

from decimal import Decimal
from uuid import uuid4

from app.modules.lms.domain.learning.block_results import (
    merge_widget,
    passed_block_ids,
    result_key,
)
from app.modules.lms.domain.learning.live import render_revision
from app.modules.lms.domain.learning.points import scored_earned_points
from app.modules.lms.domain.step_content import CodeBlock, HtmlBlock, StepContent


def test_best_score_is_kept_and_pass_is_sticky() -> None:
    first = merge_widget(None, 80, True)
    worse = merge_widget(first, 20, False)
    assert worse["pct"] == 80 and worse["passed"] is True
    better = merge_widget(worse, 100, True)
    assert better["pct"] == 100 and better["kind"] == "widget"


def test_reported_score_is_clamped() -> None:
    assert merge_widget(None, 250, False)["pct"] == 100
    assert merge_widget(None, -5, False)["pct"] == 0


def test_passed_widget_completes_but_is_unverified_and_earns_nothing() -> None:
    cards = {result_key("c"): merge_widget(None, 50, True)}
    assert passed_block_ids(cards) == {"c"}
    assert passed_block_ids({result_key("c"): merge_widget(None, 99, False)}) == set()
    assert cards[result_key("c")]["verified"] is False
    assert scored_earned_points(cards[result_key("c")], Decimal(0)) == Decimal(0)


def test_only_graded_widgets_carry_points() -> None:
    content = StepContent.model_validate(
        {
            "title": "Code",
            "blocks": [
                CodeBlock(id="g", graded=True).model_dump(),
                CodeBlock(id="u").model_dump(),
                HtmlBlock(id="h", graded=True).model_dump(),
            ],
        }
    )
    rendered = render_revision(uuid4(), content)
    assert rendered.scored_points == {"g": Decimal(0), "h": Decimal(0)}
