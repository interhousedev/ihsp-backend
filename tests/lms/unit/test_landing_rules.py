"""Who sees the landing page and who can enrol."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.modules.lms.domain.learning.entities import LearningCourse
from app.modules.lms.domain.learning.landing import can_enrol, landing_visible

import pytest

NOW = datetime(2026, 10, 1, tzinfo=UTC)
PUBLISHED = LearningCourse(
    id=uuid4(),
    slug="c",
    title="C",
    description="",
    cover_file_id=None,
    visibility="public",
    invite_code=None,
    status="active",
    live_version_id=uuid4(),
    publish_state="published",
)
DRAFT = replace(PUBLISHED, live_version_id=None, publish_state="draft")


def visible(course: LearningCourse, **kw: bool) -> bool:
    args = {"enrolled": False, "is_staff": False, "previewing": False} | kw
    return landing_visible(course, **args)


def test_draft_hidden_from_learners_visible_in_preview() -> None:
    assert not visible(DRAFT)
    assert visible(DRAFT, previewing=True)
    assert visible(DRAFT, is_staff=True)


def test_published_public_is_visible() -> None:
    assert visible(PUBLISHED)


@pytest.mark.parametrize("scope", ["link", "lyceum", "public"])
def test_scopes_other_than_group_are_visible(scope: str) -> None:
    assert visible(replace(PUBLISHED, audience_scope=scope))


def test_group_scope_and_invite_hidden_from_outsiders() -> None:
    assert not visible(replace(PUBLISHED, audience_scope="group"))
    assert visible(replace(PUBLISHED, audience_scope="group"), enrolled=True)
    assert not visible(replace(PUBLISHED, visibility="invite"))


def test_archived_hidden() -> None:
    assert not visible(replace(PUBLISHED, status="archived"))


def test_can_enrol_window() -> None:
    assert can_enrol(PUBLISHED, enrolled=False, now=NOW)
    assert not can_enrol(PUBLISHED, enrolled=True, now=NOW)
    assert not can_enrol(
        replace(PUBLISHED, enrolment_open=False), enrolled=False, now=NOW
    )
    future = replace(PUBLISHED, enrolment_starts_at=NOW + timedelta(days=1))
    assert not can_enrol(future, enrolled=False, now=NOW)
    past = replace(PUBLISHED, enrolment_ends_at=NOW - timedelta(days=1))
    assert not can_enrol(past, enrolled=False, now=NOW)
    assert not can_enrol(DRAFT, enrolled=False, now=NOW)
