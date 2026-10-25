"""Course progress and step completion rules (LMS-14, LMS-19)."""

from collections.abc import Collection


def percent(completed: int, total: int) -> int:
    """Return ``completed / total * 100`` rounded half up; 0 for an empty course."""
    if total <= 0:
        return 0
    return min(100, (completed * 200 + total) // (2 * total))


def all_tests_passed(
    test_block_ids: Collection[str], passed_block_ids: Collection[str]
) -> bool:
    """Return True when the step has tests and every one of them is passed."""
    return bool(test_block_ids) and all(
        block_id in passed_block_ids for block_id in test_block_ids
    )


def completes_on_view(test_block_ids: Collection[str]) -> bool:
    """Return True when opening the step completes it: it has no tests."""
    return not test_block_ids
