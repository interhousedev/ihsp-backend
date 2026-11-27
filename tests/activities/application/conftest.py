"""Fixtures for activities application tests.

The implementation must provide `tests/fakes/activities/__init__.py` and
`tests/fakes/activities/world.py`
(none exist yet, so collection fails with ModuleNotFoundError until they are built).
Required symbols:

  world.py
    build_world() -> ActivitiesWorld
    ActivitiesWorld
      .services: ActivitiesServices (app.modules.activities.wiring.build(deps,
      overrides)) exposing
          clubs (incl. set_capabilities), memberships, ownership, team, events, ratings,
          announcements,
          planner, drafts (DraftService), forms (FormsService), leaderboard
          (LeaderboardService),
          analytics, public, club_courses (ClubCourseService), opportunities
          (OpportunitiesService)
      .clock: FixedClock (.now(), .set(dt), .advance(**kw))
      .notifier: NotifierFake; .notifier.sent: list[NotificationDraft] recipients one
      per row, no `channel`
          attribute (delivery follows each recipient's preferences)
      .scheduled: list[NotificationDraft] (future-dated rows; .cancel_scheduled(prefix)
      removes rows by
          dedupe_key prefix); .sent: list[NotificationDraft] (immediate rows, same list
          as notifier.sent)
      .captcha.ok (bool, default True); .rate_limiter (RateLimiter fake)
      .delivered: list[NotificationDraft] (rows already delivered; .deliver_due() moves
      due `scheduled` rows
          there and keeps their dedupe_key reserved: a later insert with the same key is
          dropped, like notify's
          ON CONFLICT DO NOTHING); .audit: list of audit records (actor_id, action,
          target)
      .remove_teacher(course, teacher); .add_student_plan(student, opportunity_id);
      .plans_of(student);
      .add_legacy_opportunity(status) (pre-migration row); .run_audience_migration();
      .admission (fake
          admission student-data reader: .student_plans(actor, student_id));
      .add_team_seat(club_id, actor, position, bio=None, photo_url=None, public=False,
      consent=False) -> seat;
      .name_of(actor) -> str (display name, used to prove anonymised output does not
      leak it)
      .add_student(*, age=16, **kw) -> Actor; .add_staff(*roles) -> Actor
      .add_teacher(**kw) -> Actor (a staff actor with the TEACHER role)
      .add_course(*, teacher: Actor, **kw) -> Course (id, teacher/owner id) known to the
      course lookup port
          used by ClubCourseService and Event.course_id authz
"""

from app.shared.actor import Actor, Role
from tests.fakes.activities.world import (  # noqa: F401  (expected fakes)
    ActivitiesWorld,
    build_world,
)

import pytest


@pytest.fixture
def world() -> ActivitiesWorld:
    return build_world()


@pytest.fixture
def su(world: ActivitiesWorld) -> Actor:
    return world.add_staff(Role.SU)


@pytest.fixture
def owner(world: ActivitiesWorld) -> Actor:
    return world.add_student()


@pytest.fixture
def student(world: ActivitiesWorld) -> Actor:
    return world.add_student()


@pytest.fixture
async def club(world: ActivitiesWorld, owner: Actor, su: Actor):
    """An active, public club owned by `owner`."""
    c = await world.services.clubs.create(
        owner, name="Chess", slug="chess", description="Boards"
    )
    await world.services.clubs.submit(owner, c.id)
    await world.services.clubs.review(su, c.id, approve=True, reason=None)
    return await world.services.clubs.get(owner, c.id)


@pytest.fixture
async def volunteers(world: ActivitiesWorld, owner: Actor, su: Actor):
    """IHT Volunteers: an active club with forms, drafting, points and roster switched
    on by SU."""
    from app.modules.activities.domain.club import ClubCapability

    c = await world.services.clubs.create(
        owner, name="IHT Volunteers", slug="volunteers", description="d"
    )
    await world.services.clubs.submit(owner, c.id)
    await world.services.clubs.review(su, c.id, approve=True, reason=None)
    return await world.services.clubs.set_capabilities(su, c.id, set(ClubCapability))


@pytest.fixture
def teacher(world: ActivitiesWorld) -> Actor:
    return world.add_teacher()
