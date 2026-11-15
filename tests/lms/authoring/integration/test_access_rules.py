"""Course and lesson audience rules: who may read and change them."""

from app.modules.lms.domain.access_rules import AccessRule, Audience, WhenDenied
from app.modules.lms.domain.authoring.errors import (
    CoursePermissionError,
    SettingsInvalidError,
    StepNotFoundError,
)
from app.modules.lms.wiring_authoring import AuthoringServices
from app.shared.ids import new_id
from tests.fakes.lms.identity import FakeIdentityDirectory
from tests.lms.authoring.conftest import CourseFixture

import pytest


async def test_owner_sets_a_chosen_course_rule_and_staff_read_it(
    services: AuthoringServices,
    course: CourseFixture,
    identity: FakeIdentityDirectory,
) -> None:
    """The owner chooses people; any staff member sees the rule with names."""
    pupil = identity.add_user("pupil", last_name="Pupil")
    rule = AccessRule(Audience.CHOSEN, WhenDenied.LOCKED, (), (pupil.id, pupil.id))
    saved = await services.set_access_rule.execute(course.team.owner, course.id, rule)
    assert saved.course.audience is Audience.CHOSEN
    assert [u.id for u in saved.course.users] == [pupil.id]
    shown = await services.get_access_rules.execute(course.team.teacher, course.id)
    assert shown.course.when_denied is WhenDenied.LOCKED
    assert "Pupil" in shown.course.users[0].name


async def test_only_the_owner_or_lms_admin_change_rules(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """Teachers on staff and outsiders cannot change; outsiders cannot read."""
    rule = AccessRule(Audience.SIGNED_IN)
    with pytest.raises(CoursePermissionError):
        await services.set_access_rule.execute(course.team.teacher, course.id, rule)
    with pytest.raises(CoursePermissionError):
        await services.get_access_rules.execute(course.team.outsider, course.id)
    saved = await services.set_access_rule.execute(course.team.admin, course.id, rule)
    assert saved.course.audience is Audience.SIGNED_IN


async def test_lesson_rule_must_belong_to_the_course(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """A lesson rule is listed per step; a foreign step id is 404."""
    owner = course.team.owner
    section = await services.create_section.execute(owner, course.id, "Basics")
    step = await services.create_step.execute(
        owner, course.id, section_id=section.id, title="Intro"
    )
    saved = await services.set_access_rule.execute(
        owner, course.id, AccessRule(Audience.STUDENTS), step_id=step.step_id
    )
    assert [s.step_id for s in saved.steps] == [step.step_id]
    assert saved.course.audience is Audience.PUBLIC
    with pytest.raises(StepNotFoundError):
        await services.set_access_rule.execute(
            owner, course.id, AccessRule(Audience.STUDENTS), step_id=new_id()
        )


@pytest.mark.parametrize(
    ("rule", "field"),
    [
        (AccessRule(Audience.CHOSEN), "audience"),
        (AccessRule(Audience.CHOSEN, user_ids=(new_id(),)), "user_ids"),
    ],
)
async def test_invalid_chosen_rules_are_refused(
    services: AuthoringServices,
    course: CourseFixture,
    rule: AccessRule,
    field: str,
) -> None:
    """An empty list or an unknown person is a validation error."""
    with pytest.raises(SettingsInvalidError) as caught:
        await services.set_access_rule.execute(course.team.owner, course.id, rule)
    assert caught.value.params["field"] == field
