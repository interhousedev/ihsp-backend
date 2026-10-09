"""LIB-6, LIB-9: last write wins by `client_ts`; seconds read add up."""

import datetime as dt
from uuid import UUID

from app.modules.library.domain.reader_errors import InvalidProgressError
from app.modules.library.domain.reader_progress import (
    MAX_SECONDS_PER_REPORT,
    ReadingProgress,
    apply_progress,
)
from app.shared.ids import new_id

import pytest

NOW = dt.datetime(2026, 10, 6, 9, 0, tzinfo=dt.UTC)
USER = new_id()
ITEM = new_id()
FILE = new_id()


def write(
    current: ReadingProgress | None,
    *,
    page: int = 1,
    percent: float = 10.0,
    ago: float = 60,
    seconds: int | None = None,
    file_id: UUID = FILE,
) -> ReadingProgress | None:
    """Apply one progress report made `ago` seconds before NOW."""
    return apply_progress(
        current,
        user_id=USER,
        item_id=ITEM,
        file_id=file_id,
        locator={"page": page},
        percent=percent,
        client_ts=NOW - dt.timedelta(seconds=ago),
        seconds_read=seconds,
        now=NOW,
    )


def test_first_report_creates_the_progress() -> None:
    """LIB-6: the first report stores the position and opens the item."""
    created = write(None, page=5, percent=12.5, seconds=40)

    assert created is not None
    assert created.locator == {"page": 5}
    assert created.percent == 12.5
    assert created.seconds_read == 40
    assert created.opened_at == NOW - dt.timedelta(seconds=60)


def test_newer_report_replaces_the_position_and_adds_seconds() -> None:
    """LIB-6: a later client_ts wins; reading time accumulates."""
    first = write(None, page=5, ago=120, seconds=30)

    second = write(first, page=9, percent=30, ago=60, seconds=45)

    assert second is not None
    assert second.locator == {"page": 9}
    assert second.percent == 30
    assert second.seconds_read == 75


def test_older_report_is_ignored() -> None:
    """LIB-9: an offline write that arrives late does not move the position back."""
    newer = write(None, page=20, ago=10, seconds=10)

    assert write(newer, page=3, ago=500, seconds=99) is None


def test_report_with_the_same_client_ts_is_ignored() -> None:
    """LIB-9: a retried request is not counted twice."""
    first = write(None, page=7, ago=30, seconds=20)

    assert write(first, page=7, ago=30, seconds=20) is None


def test_future_client_ts_counts_as_now() -> None:
    """LIB-9: a phone with a wrong clock cannot freeze its own progress."""
    created = write(None, ago=-3 * 86400)

    assert created is not None
    assert created.client_ts == NOW
    assert created.opened_at == NOW


def test_seconds_per_report_are_capped_and_never_negative() -> None:
    """LIB-16: a single report cannot claim hours of reading."""
    capped = write(None, seconds=10**6)
    negative = write(None, seconds=-5)

    assert capped is not None and capped.seconds_read == MAX_SECONDS_PER_REPORT
    assert negative is not None and negative.seconds_read == 0


def test_switching_file_keeps_one_progress_per_item() -> None:
    """LIB-6: the progress row follows the file the reader has open."""
    other_file = new_id()
    first = write(None, ago=100)

    second = write(first, ago=50, file_id=other_file)

    assert second is not None and second.file_id == other_file


@pytest.mark.parametrize("percent", [-0.1, 100.1, float("nan")])
def test_percent_outside_0_to_100_is_refused(percent: float) -> None:
    """LIB-6: progress is a percentage."""
    with pytest.raises(InvalidProgressError):
        write(None, percent=percent)


def test_percent_is_rounded_to_two_decimals() -> None:
    """LIB-6: the column holds two decimals."""
    created = write(None, percent=33.33333)

    assert created is not None and created.percent == 33.33
