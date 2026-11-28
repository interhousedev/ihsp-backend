"""Step kind and estimated minutes from rendered blocks."""

from app.modules.lms.domain.learning.step_estimate import estimated_minutes, step_kind


def test_kind_is_the_first_block_type() -> None:
    assert step_kind([{"type": "video"}, {"type": "text"}]) == "video"
    assert step_kind([]) is None


def test_minutes_sum_reading_and_questions() -> None:
    text = {"type": "text", "markdown": "word " * 400}
    test = {"type": "test", "rules": {"questions": 3, "time_limit_sec": None}}
    assert estimated_minutes([text]) == 2
    assert estimated_minutes([text, test]) == 5
    assert estimated_minutes([]) is None
    assert estimated_minutes([{"type": "video"}]) == 1
