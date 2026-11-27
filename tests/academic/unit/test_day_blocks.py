"""Non-lesson blocks: validation and the per-date occurrences of a student."""

import datetime as dt
from uuid import uuid4

from app.modules.academic.domain.day_blocks import (
    DayBlock,
    DayBlockInvalidError,
    occurrences,
)

import pytest

GROUP = uuid4()
OTHER = uuid4()
MONDAY = dt.date(2026, 11, 23)


def block(**fields: object) -> DayBlock:
    data: dict[str, object] = {
        "id": uuid4(),
        "name": "Lunch",
        "kind": "lunch",
        "starts_at": dt.time(12, 0),
        "ends_at": dt.time(12, 40),
        "weekdays": [1, 2, 3, 4, 5],
        "scope": "all",
    }
    data.update(fields)
    return DayBlock(**data)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "fields",
    [
        {"name": "  "},
        {"ends_at": dt.time(12, 0)},
        {"weekdays": []},
        {"weekdays": [6]},
        {"scope": "course"},
        {"scope": "groups"},
    ],
)
def test_invalid_blocks_are_rejected(fields: dict[str, object]) -> None:
    with pytest.raises(DayBlockInvalidError):
        block(**fields).validate()


def test_validate_normalises_days_and_drops_unused_scope_fields() -> None:
    item = block(weekdays=[3, 1, 3], course=2, group_ids=[GROUP])
    item.validate()
    assert item.weekdays == [1, 3]
    assert item.course is None
    assert item.group_ids == []


def test_occurrences_follow_days_course_and_groups() -> None:
    everyone = block(weekdays=[1, 2])
    second_year = block(name="Second lunch", scope="course", course=2, weekdays=[1])
    other_group = block(name="Assembly", scope="groups", group_ids=[OTHER])
    found = occurrences(
        [everyone, second_year, other_group],
        MONDAY,
        MONDAY + dt.timedelta(days=6),
        GROUP,
        2,
    )
    assert [(item.date.isoweekday(), item.name) for item in found] == [
        (1, "Lunch"),
        (1, "Second lunch"),
        (2, "Lunch"),
    ]
