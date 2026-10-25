"""Course settings, join code and link check on the real database."""

from app.modules.lms.application.authoring.validate_links import ValidateLinks
from app.modules.lms.domain.authoring.errors import (
    CoursePermissionError,
    SettingsInvalidError,
)
from app.modules.lms.infrastructure.authoring.uow import SqlAuthoringUnitOfWork
from app.modules.lms.wiring_authoring import AuthoringServices
from app.shared.db.uow_testing import noop_audit_writer, noop_outbox_writer
from tests.fakes.clock import FixedClock
from tests.fakes.lms.link_checker import FakeLinkChecker
from tests.lms.authoring.conftest import CourseFixture

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def test_settings_roundtrip(
    services: AuthoringServices, course: CourseFixture
) -> None:
    owner = course.team.owner
    before = await services.get_course_settings.execute(owner, course.id)
    assert before.publish_state == "draft" and before.language == "ru"
    assert before.stats.staff_by_role["Owner"] == 1
    after = await services.update_course_details.execute(
        owner,
        course.id,
        {"accent_color": "#0A0B0C", "tags": ["math"], "level": "beginner"},
    )
    assert after.accent_color == "#0a0b0c" and after.tags == ["math"]
    assert [i["key"] for i in after.navigation][0] == "overview"
    with pytest.raises(SettingsInvalidError):
        await services.update_course_details.execute(
            owner, course.id, {"duration_weeks": 99}
        )


async def test_outsider_cannot_read_or_write(
    services: AuthoringServices, course: CourseFixture
) -> None:
    with pytest.raises(CoursePermissionError):
        await services.get_course_settings.execute(course.team.outsider, course.id)
    with pytest.raises(CoursePermissionError):
        await services.regenerate_join_code.execute(course.team.outsider, course.id)


async def test_join_code_changes(
    services: AuthoringServices, course: CourseFixture
) -> None:
    a = await services.regenerate_join_code.execute(course.team.owner, course.id)
    b = await services.regenerate_join_code.execute(course.team.owner, course.id)
    assert a.invite_code != b.invite_code
    shown = await services.get_course_settings.execute(course.team.owner, course.id)
    assert shown.invite_code == b.invite_code


async def test_link_check_report(
    services: AuthoringServices,
    course: CourseFixture,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
    clock: FixedClock,
) -> None:
    owner = course.team.owner
    section = await services.create_section.execute(owner, course.id, "S")
    step = await services.create_step.execute(
        owner, course.id, section_id=section.id, title="Links"
    )
    assert (await services.get_link_report.execute(owner, course.id)).status == "idle"
    job = await services.start_link_check.execute(owner, course.id)
    assert (
        await services.get_link_report.execute(owner, course.id)
    ).status == "running"
    again = await services.start_link_check.execute(owner, course.id)
    assert again.job_id == job.job_id

    def uow() -> SqlAuthoringUnitOfWork:
        return SqlAuthoringUnitOfWork(
            sessionmaker_in_tx, noop_outbox_writer, noop_audit_writer
        )

    checker = FakeLinkChecker()
    runner = ValidateLinks(uow, checker, clock)
    assert await runner.execute(course.id, "stale-job") == 0
    await runner.execute(course.id, job.job_id)
    report = await services.get_link_report.execute(owner, course.id)
    assert report.status == "done" and report.checked_at is not None
    assert step.step_id is not None and report.results == []
