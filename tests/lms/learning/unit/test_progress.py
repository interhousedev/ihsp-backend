"""LMS-14, LMS-19: progress percentage and step completion rules."""

from app.modules.lms.domain.learning.progress import (
    all_tests_passed,
    completes_on_view,
    percent,
)

import pytest


@pytest.mark.parametrize(
    ("done", "total", "expected"),
    [(0, 0, 0), (0, 4, 0), (1, 3, 33), (2, 3, 67), (1, 8, 13), (3, 8, 38), (4, 4, 100)],
)
def test_progress_is_rounded_half_up(done: int, total: int, expected: int) -> None:
    """LMS-19: completed steps / steps x 100, rounded."""
    assert percent(done, total) == expected


def test_a_step_with_tests_completes_when_every_test_is_passed() -> None:
    """LMS-19: all tests passed."""
    assert all_tests_passed(["a", "b"], {"a", "b", "c"}) is True
    assert all_tests_passed(["a", "b"], {"a"}) is False


def test_a_step_without_tests_is_not_completed_by_attempts() -> None:
    """LMS-19: it completes by being opened instead."""
    assert all_tests_passed([], {"a"}) is False
    assert completes_on_view([]) is True
    assert completes_on_view(["a"]) is False
