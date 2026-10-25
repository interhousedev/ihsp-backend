"""Course settings validation."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.modules.lms.domain.authoring.course_settings import (
    apply_settings,
    default_navigation,
    to_settings,
)
from app.modules.lms.domain.authoring.entities import Course
from app.modules.lms.domain.authoring.enums import CourseStatus, Visibility
from app.modules.lms.domain.authoring.errors import SettingsInvalidError

import pytest


def make_course() -> Course:
    return Course(
        id=uuid4(),
        slug="calculus",
        title="Calculus",
        description="",
        visibility=Visibility.PUBLIC,
        status=CourseStatus.ACTIVE,
        created_by=uuid4(),
        draft_meta={},
        draft_outline={"sections": []},
        outline_hash="x",
    )


def test_valid_change_is_applied_and_normalised() -> None:
    course = make_course()
    apply_settings(
        course,
        {
            "accent_color": "#AABBCC",
            "tags": [" a ", "a", "", "b"],
            "workload_hours_per_week": 40,
            "duration_weeks": 1,
            "level": None,
            "summary": "  hi ",
        },
    )
    assert course.accent_color == "#aabbcc"
    assert course.tags == ["a", "b"]
    assert course.summary == "hi"
    assert to_settings(course).navigation == default_navigation()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("accent_color", "red"),
        ("accent_color", "#12345"),
        ("accent_color", "#12345g"),
        ("language", "de"),
        ("level", "expert"),
        ("audience_scope", "world"),
        ("workload_hours_per_week", 0),
        ("workload_hours_per_week", 41),
        ("duration_weeks", 53),
        ("tags", [str(i) for i in range(11)]),
        ("tags", ["x" * 33]),
        ("outcomes", ["a"] * 0 + [str(i) for i in range(13)]),
        ("outcomes", ["x" * 201]),
        ("summary", "x" * 501),
        ("navigation", [{"key": "nope", "hidden": False}]),
        ("navigation", [{"key": "files"}, {"key": "files"}]),
    ],
)
def test_invalid_values_are_rejected(field: str, value: Any) -> None:
    course = make_course()
    with pytest.raises(SettingsInvalidError) as info:
        apply_settings(course, {field: value})
    assert info.value.params["field"] == field


def test_enrolment_end_must_follow_start() -> None:
    course = make_course()
    start = datetime(2026, 9, 1, tzinfo=UTC)
    apply_settings(course, {"enrolment_starts_at": start})
    with pytest.raises(SettingsInvalidError):
        apply_settings(course, {"enrolment_ends_at": start})
    apply_settings(course, {"enrolment_ends_at": datetime(2026, 9, 2, tzinfo=UTC)})


def test_failed_change_leaves_course_untouched() -> None:
    course = make_course()
    with pytest.raises(SettingsInvalidError):
        apply_settings(course, {"summary": "ok", "language": "de"})
    assert course.summary == ""
