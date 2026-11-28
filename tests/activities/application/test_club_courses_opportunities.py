"""Club<->course link (two-party consent), course-linked events, ONE opportunities
catalog (spec 4.14).

ClubCourseService (club_courses):
  .request(actor, club_id, course_id) -> ClubCourseLink (status 'pending', or 'active'
  at once when the actor
    holds BOTH sides, which no student does); the requester must be the club owner OR a
    teacher/owner of the
    course (CourseLinkDeniedError otherwise);
  .confirm(actor, club_id, course_id) -> link 'active': the OTHER side confirms, with
  both scopes re-read at
    confirmation time (an ex-owner or a teacher removed from the course is denied);
  .unlink(actor, club_id, course_id): either side, also cancels/declines a pending
  request;
  .for_club(actor, club_id) / .for_course(actor, course_id): active links for anyone
  allowed to see the club/
    course; pending ones only for the two parties (a stranger sees neither the pending
    request nor that the
    course exists beyond its public name).
events.create(..., course_id=None, opportunity_id=None): course_id needs an ACTIVE link
between that club and
  that course (and the actor an organizer of the club); otherwise CourseLinkDeniedError.
Opportunities (`opportunities`, activities module OVER the admission
`OpportunityCatalog` contract; ONE catalog,
no second table). It keeps admission's typed `kind`, validation, optimistic lock and
audit:
  .create(admin, kind, title, audience, **draft_fields) -> Opportunity (kind required;
  the admission
    OpportunityDraft validation applies: ValidationFailedError(field),
    InvalidProofUrlError for non-https);
  .update(admin, id, draft_fields..., audience, lock_version) (stale lock_version ->
  AdmissionConflictError);
  .archive(admin, id, archived) / .delete(admin, id) (CatalogInUseError when a student
  plan, a comment or an
    activity event references it: archive instead; nothing cascades); .list(actor,
    surface); .get(actor, id,
    surface).
  Fake world extras: world.add_student_plan(student, opportunity_id),
  world.add_legacy_opportunity(status=...)
  (a row as it exists BEFORE the audience migration), world.run_audience_migration(),
  world.admission.student_plans(actor, student_id) (admission student data).
"""

import inspect
from datetime import UTC, datetime, timedelta
from typing import Any

from app.modules.activities.domain.access import PermissionDeniedError
from app.modules.activities.domain.course_link import (
    CourseLinkDeniedError,
    CourseLinkExistsError,
)
from app.modules.admission.domain.errors import (
    AdmissionConflictError,
    CatalogInUseError,
)
from app.shared.actor import Actor, Role
from app.shared.base_error import ForbiddenError, NotFoundError, ValidationFailedError
from tests.fakes.activities.world import ActivitiesWorld

import pytest


async def _club(
    world: ActivitiesWorld, owner: Actor, su: Actor, slug: str = "volunteers"
) -> Any:
    c = await world.services.clubs.create(
        owner, name="Volunteers", slug=slug, description="d"
    )
    await world.services.clubs.submit(owner, c.id)
    await world.services.clubs.review(su, c.id, approve=True, reason=None)
    return c


# ---- club <-> course ----------------------------------------------------------


async def test_link_is_a_two_party_request_and_accept(
    world: ActivitiesWorld, student: Actor, su: Actor
) -> None:
    teacher = world.add_teacher()
    course = world.add_course(teacher=teacher)
    club = await _club(world, student, su)
    svc = world.services.club_courses
    stranger, stray_teacher = world.add_student(), world.add_teacher()
    for who in (
        stranger,
        stray_teacher,
    ):  # neither the club owner nor a teacher of this course
        with pytest.raises(CourseLinkDeniedError):
            await svc.request(who, club.id, course.id)
    pending = await svc.request(student, club.id, course.id)
    assert pending.status == "pending"
    assert (
        await svc.for_club(stranger, club.id) == []
        and await svc.for_course(stranger, course.id) == []
    )
    assert [
        x.course_id for x in await svc.for_club(teacher, club.id)
    ] == []  # not active yet: not listed
    with pytest.raises(CourseLinkDeniedError):
        await svc.confirm(
            student, club.id, course.id
        )  # the requester cannot confirm their own request
    with pytest.raises(CourseLinkDeniedError):
        await svc.confirm(
            stray_teacher, club.id, course.id
        )  # a teacher of a different course
    with pytest.raises(CourseLinkExistsError):
        await svc.request(teacher, club.id, course.id)  # one pair, pending or active
    active = await svc.confirm(teacher, club.id, course.id)
    assert active.status == "active"
    assert [x.course_id for x in await svc.for_club(student, club.id)] == [course.id]
    assert [x.club_id for x in await svc.for_course(teacher, course.id)] == [club.id]
    await svc.unlink(teacher, club.id, course.id)  # either side may end it
    assert await svc.for_club(student, club.id) == []


async def test_teacher_can_start_the_request_and_the_club_owner_confirms(
    world: ActivitiesWorld, student: Actor, su: Actor
) -> None:
    teacher = world.add_teacher()
    course = world.add_course(teacher=teacher)
    club = await _club(world, student, su)
    svc = world.services.club_courses
    await svc.request(teacher, club.id, course.id)
    with pytest.raises(CourseLinkDeniedError):
        await svc.confirm(world.add_student(), club.id, course.id)
    await svc.confirm(student, club.id, course.id)
    assert [x.course_id for x in await svc.for_club(student, club.id)] == [course.id]


async def test_confirmation_rechecks_both_scopes(
    world: ActivitiesWorld, student: Actor, su: Actor
) -> None:
    teacher = world.add_teacher()
    course = world.add_course(teacher=teacher)
    club = await _club(world, student, su)
    heir = world.add_student()
    await world.services.memberships.join(heir, club.id)
    await world.services.memberships.approve(student, club.id, heir.user_id)
    svc = world.services.club_courses
    await svc.request(teacher, club.id, course.id)
    t = await world.services.ownership.offer(student, club.id, heir.user_id)
    await world.services.ownership.accept(heir, t.id)
    with pytest.raises(
        CourseLinkDeniedError
    ):  # the previous owner is no longer the club's owner
        await svc.confirm(student, club.id, course.id)
    await svc.confirm(heir, club.id, course.id)
    world.remove_teacher(course, teacher)  # course side lost
    with pytest.raises(CourseLinkDeniedError):
        await svc.unlink(teacher, club.id, course.id)


async def test_decline_by_unlinking_a_pending_request(
    world: ActivitiesWorld, student: Actor, su: Actor
) -> None:
    teacher = world.add_teacher()
    course = world.add_course(teacher=teacher)
    club = await _club(world, student, su)
    await world.services.club_courses.request(student, club.id, course.id)
    await world.services.club_courses.unlink(teacher, club.id, course.id)
    with pytest.raises(NotFoundError):
        await world.services.club_courses.confirm(teacher, club.id, course.id)


async def test_event_links_only_an_active_course_link(
    world: ActivitiesWorld, student: Actor, su: Actor
) -> None:
    teacher = world.add_teacher()
    course = world.add_course(teacher=teacher)
    club = await _club(world, student, su)
    start = datetime.now(UTC) + timedelta(days=2)
    kw = {
        "title": {"en": "Talk"},
        "starts_at": start,
        "ends_at": start + timedelta(hours=1),
    }
    with pytest.raises(CourseLinkDeniedError):  # no link at all
        await world.services.events.create(student, club.id, course_id=course.id, **kw)
    await world.services.club_courses.request(student, club.id, course.id)
    with pytest.raises(CourseLinkDeniedError):  # pending is not consent yet
        await world.services.events.create(student, club.id, course_id=course.id, **kw)
    await world.services.club_courses.confirm(teacher, club.id, course.id)
    ev = await world.services.events.create(student, club.id, course_id=course.id, **kw)
    assert ev.course_id == course.id
    foreign = world.add_course(teacher=world.add_teacher())
    with pytest.raises(CourseLinkDeniedError):
        await world.services.events.create(student, club.id, course_id=foreign.id, **kw)


# ---- one opportunities catalog ------------------------------------------------

BOTH = frozenset({"admission", "my_iht"})


@pytest.fixture
def admin(world: ActivitiesWorld):
    return world.add_staff(Role.ACTIVITIES_ADMIN)


async def test_signature_keeps_the_typed_kind_and_the_optimistic_lock(
    world: ActivitiesWorld,
) -> None:
    svc = world.services.opportunities
    assert (
        inspect.signature(svc.create).parameters["kind"].default
        is inspect.Parameter.empty
    )
    assert "lock_version" in inspect.signature(svc.update).parameters


async def test_create_validates_like_admission(
    world: ActivitiesWorld, admin: Actor
) -> None:
    svc = world.services.opportunities
    with pytest.raises(ValidationFailedError):
        await svc.create(admin, kind="exam", title="", audience=BOTH)
    with pytest.raises(ValidationFailedError):
        await svc.create(admin, kind="not-a-kind", title="x", audience=BOTH)
    with pytest.raises(Exception) as bad_url:
        await svc.create(
            admin,
            kind="exam",
            title="SAT",
            url="http://insecure.example",
            audience=BOTH,
        )
    assert getattr(bad_url.value, "code", "") == "admission/invalid_proof_url"
    assert [a.action for a in world.audit if a.action.startswith("opportunity.")] == []


async def test_audience_filters_lists_and_details(
    world: ActivitiesWorld, admin: Actor, student: Actor
) -> None:
    svc = world.services.opportunities
    both = await svc.create(admin, kind="exam", title="Olympiad", audience=BOTH)
    adm_only = await svc.create(
        admin, kind="exam", title="SAT prep", audience=frozenset({"admission"})
    )
    assert [o.id for o in await svc.list(student, surface="my_iht")] == [both.id]
    assert {o.id for o in await svc.list(student, surface="admission")} == {
        both.id,
        adm_only.id,
    }
    assert (await svc.get(student, both.id, surface="my_iht")).id == both.id
    with pytest.raises(
        NotFoundError
    ):  # details obey the audience too, no enumeration through the id
        await svc.get(student, adm_only.id, surface="my_iht")
    upd = await svc.update(
        admin,
        adm_only.id,
        kind="exam",
        title="SAT prep",
        audience=BOTH,
        lock_version=adm_only.lock_version,
    )
    assert {o.id for o in await svc.list(student, surface="my_iht")} == {
        both.id,
        adm_only.id,
    }
    with pytest.raises(AdmissionConflictError):  # stale version
        await svc.update(
            admin,
            adm_only.id,
            kind="exam",
            title="x",
            audience=BOTH,
            lock_version=adm_only.lock_version,
        )
    assert upd.lock_version == adm_only.lock_version + 1
    assert {"opportunity.staff_created", "opportunity.staff_edited"} <= {
        a.action for a in world.audit
    }


async def test_archived_and_pending_items_never_reach_my_iht(
    world: ActivitiesWorld, admin: Actor, student: Actor
) -> None:
    svc = world.services.opportunities
    o = await svc.create(admin, kind="exam", title="Olympiad", audience=BOTH)
    await svc.archive(admin, o.id, True)
    assert await svc.list(student, surface="my_iht") == []
    with pytest.raises(NotFoundError):
        await svc.get(student, o.id, surface="my_iht")
    pending = world.add_legacy_opportunity(
        status="pending"
    )  # a student proposal awaiting moderation
    world.run_audience_migration()
    assert pending.id not in {x.id for x in await svc.list(student, surface="my_iht")}


async def test_existing_admission_opportunities_appear_in_my_iht_after_the_migration(
    world: ActivitiesWorld, student: Actor
) -> None:
    approved = world.add_legacy_opportunity(status="approved")
    pending = world.add_legacy_opportunity(status="pending")
    rejected = world.add_legacy_opportunity(status="rejected")
    svc = world.services.opportunities
    assert (
        await svc.list(student, surface="my_iht") == []
    )  # before: audience column empty
    world.run_audience_migration()
    assert {o.id for o in await svc.list(student, surface="my_iht")} == {approved.id}
    assert {o.id for o in await svc.list(student, surface="admission")} >= {approved.id}
    assert pending.id not in {o.id for o in await svc.list(student, surface="my_iht")}
    assert rejected.id not in {o.id for o in await svc.list(student, surface="my_iht")}


async def test_delete_in_use_is_refused_and_archive_is_the_way(
    world: ActivitiesWorld, admin: Actor, student: Actor
) -> None:
    svc = world.services.opportunities
    planned = await svc.create(admin, kind="exam", title="Planned", audience=BOTH)
    world.add_student_plan(student, planned.id)
    with pytest.raises(CatalogInUseError):
        await svc.delete(admin, planned.id)
    assert world.plans_of(student) != []  # the plan survived: nothing cascaded
    await svc.archive(admin, planned.id, True)

    owner = world.add_student()
    club = await _club(world, owner, world.add_staff(Role.SU))
    referenced = await svc.create(admin, kind="event", title="Fair", audience=BOTH)
    start = datetime.now(UTC) + timedelta(days=2)
    await world.services.events.create(
        owner,
        club.id,
        title={"en": "Fair stand"},
        starts_at=start,
        ends_at=start + timedelta(hours=1),
        opportunity_id=referenced.id,
    )
    with pytest.raises(CatalogInUseError):  # an activity event references it
        await svc.delete(admin, referenced.id)

    free = await svc.create(admin, kind="exam", title="Unused", audience=BOTH)
    await svc.delete(admin, free.id)
    assert free.id not in {o.id for o in await svc.list(admin, surface="admission")}
    assert "opportunity.staff_deleted" in {a.action for a in world.audit}


async def test_only_admin_and_activities_admin_manage_the_catalog(
    world: ActivitiesWorld, student: Actor, su: Actor
) -> None:
    svc = world.services.opportunities
    for who in (student, su):  # SU is a student-held role: no catalog authority
        with pytest.raises(ForbiddenError):
            await svc.create(who, kind="exam", title="x", audience=BOTH)
    for role in (Role.ADMIN, Role.ACTIVITIES_ADMIN):
        o = await svc.create(
            world.add_staff(role), kind="exam", title=f"by-{role.value}", audience=BOTH
        )
        with pytest.raises(ForbiddenError):
            await svc.update(
                su,
                o.id,
                kind="exam",
                title="y",
                audience=BOTH,
                lock_version=o.lock_version,
            )
        with pytest.raises(ForbiddenError):
            await svc.archive(su, o.id, True)
        with pytest.raises(ForbiddenError):
            await svc.delete(su, o.id)


async def test_activities_admin_gets_no_admission_student_data(
    world: ActivitiesWorld, admin: Actor, student: Actor
) -> None:
    world.add_student_plan(
        student,
        (
            await world.services.opportunities.create(
                admin, kind="exam", title="P", audience=BOTH
            )
        ).id,
    )
    with pytest.raises((ForbiddenError, PermissionDeniedError)):
        await world.admission.student_plans(admin, student.user_id)
