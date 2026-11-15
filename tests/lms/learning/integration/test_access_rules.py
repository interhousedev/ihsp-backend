"""Audience rules: who may see and open courses and lessons on every read path."""

from datetime import datetime, timedelta
from uuid import UUID

from app.modules.lms.domain.access_rules import AccessRule, Audience, WhenDenied
from app.modules.lms.domain.learning.errors import (
    ContentLockedError,
    CourseNotFoundError,
    StepNotFoundError,
)
from app.modules.lms.infrastructure.access_rule_repository import (
    SqlAccessRuleRepository,
)
from app.modules.lms.infrastructure.orm.access_rule import (
    AccessRule as CourseAccessRule,
)
from app.modules.lms.infrastructure.orm.course import Course
from app.modules.lms.wiring_learning import LearningServices, build_learning
from app.shared.actor import Actor
from app.shared.contracts.identity import TelegramAccountRef
from app.shared.ids import new_id
from app.shared.wiring import ModuleDeps
from tests.fakes.clock import FixedClock
from tests.lms.learning.builders import SeededCourse, add_staff, content, quiz
from tests.lms.learning.builders import seed_course as seed_draft
from tests.lms.learning.builders import text_block
from tests.lms.learning.fakes.identity import FakeIdentityDirectory
from tests.lms.learning.fakes.preview_revisions import FakePreviewRevisions
from tests.lms.learning.scenarios import QUESTIONS, RIGHT, quiz_course

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

STEPS = [
    ("s1", content("Intro", text_block())),
    ("s2", content("Secret", text_block())),
]
GROUP = new_id()


async def seed_course(
    maker: async_sessionmaker[AsyncSession], **options: object
) -> SeededCourse:
    """A course published for learners and guests."""
    course = await seed_draft(maker, **options)  # type: ignore[arg-type]
    async with maker() as session:
        await session.execute(
            update(Course)
            .where(Course.id == course.id)
            .values(publish_state="published")
        )
        await session.commit()
    return course


@pytest.fixture
def groups() -> dict[UUID, UUID]:
    """Active student id -> group id, read by the gate."""
    return {}


@pytest.fixture
def gated(
    deps: ModuleDeps,
    identity: FakeIdentityDirectory,
    previews: FakePreviewRevisions,
    groups: dict[UUID, UUID],
) -> LearningServices:
    """Learning services with a student group lookup."""

    async def lookup(user_id: UUID) -> UUID | None:
        return groups.get(user_id)

    return build_learning(
        deps, identity=identity, preview_revisions=previews, student_group=lookup
    )


async def restrict(
    maker: async_sessionmaker[AsyncSession],
    course: SeededCourse,
    rule: AccessRule,
    target: UUID | None = None,
) -> None:
    """Store a rule for the course or one of its steps."""
    async with maker() as session:
        await SqlAccessRuleRepository(session).save(
            course.id, target or course.id, rule, course.created_by
        )
        await session.commit()


def chosen(
    when: WhenDenied, *, groups: tuple[UUID, ...] = (), users: tuple[UUID, ...] = ()
) -> AccessRule:
    """A chosen-audience rule."""
    return AccessRule(Audience.CHOSEN, when, groups, users)


async def test_guest_sees_public_course_but_not_signed_in_one(
    maker: async_sessionmaker[AsyncSession], gated: LearningServices
) -> None:
    """A guest reads public courses; a hidden signed-in course looks missing."""
    open_course = await seed_course(maker, steps=STEPS, slug="open")
    members = await seed_course(maker, steps=STEPS, slug="members")
    await restrict(maker, members, AccessRule(Audience.SIGNED_IN))

    slugs = [card.slug for card in await gated.public_courses.catalog()]
    assert "open" in slugs and "members" not in slugs
    assert (await gated.public_courses.page("open")).slug == "open"
    with pytest.raises(CourseNotFoundError):
        await gated.public_courses.page("members")
    step = open_course.step("s1").step_id
    assert (await gated.public_courses.step(open_course.id, step)).step_id == step
    with pytest.raises((CourseNotFoundError, StepNotFoundError)):
        await gated.public_courses.step(members.id, members.step("s1").step_id)


async def test_guest_page_shows_staff_names_only(
    maker: async_sessionmaker[AsyncSession],
    gated: LearningServices,
    identity: FakeIdentityDirectory,
) -> None:
    """The guest page never carries logins or permissions of the staff."""
    course = await seed_course(maker, steps=STEPS)
    lead = identity.add(first_name="Gavxar", last_name="Kalandarova")
    await add_staff(maker, course, lead.id, role="Teacher")

    page = await gated.public_courses.page(course.slug)

    dumped = page.model_dump()
    assert [set(item) for item in dumped["staff"]] == [{"name", "position"}]
    assert "Kalandarova" in dumped["staff"][0]["name"]


async def test_locked_course_is_listed_but_closed(
    maker: async_sessionmaker[AsyncSession],
    gated: LearningServices,
    identity: FakeIdentityDirectory,
    student: Actor,
) -> None:
    """A locked course shows a lock; enrolling and reading steps are refused."""
    lead = identity.add(first_name="Dilnoza", last_name="Karimova")
    course = await seed_course(maker, steps=STEPS, created_by=lead.id)
    await restrict(maker, course, chosen(WhenDenied.LOCKED, users=(new_id(),)))

    cards = await gated.list_catalog.execute(actor=student)
    card = next(c for c in cards if c.slug == course.slug)
    assert card.locked is True and card.access == "chosen"
    page = await gated.get_course_page.execute(student, course.slug)
    assert page.locked is True
    assert page.contact is not None
    with pytest.raises(ContentLockedError):
        await gated.enroll_in_course.execute(student, course.id)
    with pytest.raises(ContentLockedError):
        await gated.get_step_view.execute(student, course.id, course.step("s1").step_id)
    landing = await gated.get_course_landing.execute(student, course.slug)
    assert landing.enrolment.can_enrol is False


async def test_hidden_course_looks_missing(
    maker: async_sessionmaker[AsyncSession],
    gated: LearningServices,
    student: Actor,
) -> None:
    """A hidden course is absent from the catalogue and its page is a 404."""
    course = await seed_course(maker, steps=STEPS)
    await restrict(maker, course, chosen(WhenDenied.HIDDEN, users=(new_id(),)))

    cards = await gated.list_catalog.execute(actor=student)
    assert course.slug not in [c.slug for c in cards]
    with pytest.raises(CourseNotFoundError):
        await gated.get_course_page.execute(student, course.slug)


async def test_chosen_by_user_and_by_group_admit_the_listed_people(
    maker: async_sessionmaker[AsyncSession],
    gated: LearningServices,
    groups: dict[UUID, UUID],
    student: Actor,
    other_student: Actor,
) -> None:
    """A listed user and a member of a listed group read the course."""
    by_user = await seed_course(maker, steps=STEPS, slug="by-user")
    by_group = await seed_course(maker, steps=STEPS, slug="by-group")
    await restrict(maker, by_user, chosen(WhenDenied.HIDDEN, users=(student.user_id,)))
    await restrict(maker, by_group, chosen(WhenDenied.HIDDEN, groups=(GROUP,)))
    groups[other_student.user_id] = GROUP

    assert (await gated.get_course_page.execute(student, "by-user")).locked is False
    with pytest.raises(CourseNotFoundError):
        await gated.get_course_page.execute(other_student, "by-user")
    page = await gated.get_course_page.execute(other_student, "by-group")
    assert page.locked is False
    with pytest.raises(CourseNotFoundError):
        await gated.get_course_page.execute(student, "by-group")


async def test_students_audience_excludes_teachers_who_are_not_staff(
    maker: async_sessionmaker[AsyncSession],
    gated: LearningServices,
    student: Actor,
    teacher: Actor,
) -> None:
    """`students` admits students only; other signed-in users are refused."""
    course = await seed_course(maker, steps=STEPS)
    await restrict(maker, course, AccessRule(Audience.STUDENTS, WhenDenied.LOCKED))

    assert (await gated.get_course_page.execute(student, course.slug)).locked is False
    page = await gated.get_course_page.execute(teacher, course.slug)
    assert page.locked is True
    assert page.contact is None


async def test_lesson_rule_locks_one_step_inside_an_open_course(
    maker: async_sessionmaker[AsyncSession],
    gated: LearningServices,
    student: Actor,
) -> None:
    """The locked lesson stays in the outline with a lock; reading it is refused."""
    course = await seed_course(maker, steps=STEPS)
    secret = course.step("s2").step_id
    await restrict(maker, course, chosen(WhenDenied.LOCKED, users=(new_id(),)), secret)
    await gated.enroll_in_course.execute(student, course.id)

    page = await gated.get_course_page.execute(student, course.slug)
    steps = {s.step_id: s for sec in page.outline for s in sec.steps}
    assert steps[secret].locked is True and steps[secret].access == "chosen"
    assert steps[course.step("s1").step_id].locked is False
    await gated.get_step_view.execute(student, course.id, course.step("s1").step_id)
    with pytest.raises(ContentLockedError):
        await gated.get_step_view.execute(student, course.id, secret)


async def test_hidden_lesson_is_dropped_from_the_outline(
    maker: async_sessionmaker[AsyncSession],
    gated: LearningServices,
    student: Actor,
) -> None:
    """A hidden lesson is missing from the outline and its content is a 404."""
    course = await seed_course(maker, steps=STEPS)
    secret = course.step("s2").step_id
    await restrict(maker, course, AccessRule(Audience.SIGNED_IN), secret)

    page = await gated.get_course_page.execute(student, course.slug)
    ids = [s.step_id for sec in page.outline for s in sec.steps]
    assert secret in ids
    guest = await gated.public_courses.page(course.slug)
    assert secret not in [s.step_id for sec in guest.outline for s in sec.steps]
    with pytest.raises((CourseNotFoundError, StepNotFoundError)):
        await gated.public_courses.step(course.id, secret)


async def test_course_staff_and_lms_admin_bypass_the_rules(
    maker: async_sessionmaker[AsyncSession],
    gated: LearningServices,
    teacher: Actor,
    lms_admin: Actor,
) -> None:
    """Course staff and LMS administrators always open everything."""
    course = await seed_course(maker, steps=STEPS)
    secret = course.step("s2").step_id
    await restrict(maker, course, chosen(WhenDenied.HIDDEN, users=(new_id(),)))
    await restrict(maker, course, chosen(WhenDenied.HIDDEN, users=(new_id(),)), secret)
    await add_staff(maker, course, teacher.user_id)

    for actor in (teacher, lms_admin):
        page = await gated.get_course_page.execute(actor, course.slug)
        assert page.locked is False
        assert secret in [s.step_id for sec in page.outline for s in sec.steps]


async def test_hidden_lesson_is_left_out_of_counts_and_points(
    maker: async_sessionmaker[AsyncSession], gated: LearningServices
) -> None:
    """Guests count and score only the lessons they can see."""
    course = await seed_course(
        maker,
        steps=[*STEPS, ("quiz", content("Quiz", quiz("quiz", QUESTIONS)))],
    )
    open_page = await gated.public_courses.page(course.slug)
    await restrict(
        maker, course, AccessRule(Audience.SIGNED_IN), course.step("quiz").step_id
    )

    page = await gated.public_courses.page(course.slug)
    card = next(c for c in await gated.public_courses.catalog() if c.id == course.id)
    assert open_page.steps_count == 3 and open_page.points_total > 0
    assert page.steps_count == card.steps_count == 2
    assert page.points_total == 0


async def test_progress_reaches_100_when_every_visible_lesson_is_done(
    maker: async_sessionmaker[AsyncSession],
    gated: LearningServices,
    student: Actor,
) -> None:
    """A lesson the learner cannot open does not hold progress below 100%."""
    course = await seed_course(maker, steps=STEPS)
    secret = course.step("s2").step_id
    await restrict(maker, course, chosen(WhenDenied.LOCKED, users=(new_id(),)), secret)
    await gated.enroll_in_course.execute(student, course.id)

    await gated.mark_step_viewed.execute(student, course.step("s1").step_id)

    page = await gated.get_course_page.execute(student, course.slug)
    assert page.steps_count == 2
    assert page.progress_pct == 100


async def test_started_attempt_can_be_finished_after_the_lesson_is_locked(
    maker: async_sessionmaker[AsyncSession],
    gated: LearningServices,
    student: Actor,
) -> None:
    """A rule change does not strand an attempt already under way."""
    course, step = await quiz_course(maker, gated, student)
    attempt = await gated.start_attempt.execute(
        student, step.step_id, "quiz", preview=False
    )
    await restrict(
        maker, course, chosen(WhenDenied.LOCKED, users=(new_id(),)), step.step_id
    )

    await gated.save_answers.execute(student, attempt.id, RIGHT)
    result = await gated.submit_attempt.execute(student, attempt.id)

    assert result.submitted_at is not None
    with pytest.raises(ContentLockedError):
        await gated.start_attempt.execute(student, step.step_id, "quiz", preview=False)


async def test_saving_a_rule_again_moves_its_updated_at(
    maker: async_sessionmaker[AsyncSession], clock: FixedClock
) -> None:
    """The upsert stamps the change time, not only the first insert."""
    course = await seed_course(maker, steps=STEPS)

    async def stamp() -> datetime:
        async with maker() as session:
            value = await session.scalar(
                select(CourseAccessRule.updated_at).where(
                    CourseAccessRule.target_id == course.id
                )
            )
        assert value is not None
        return value

    await restrict(maker, course, AccessRule(Audience.SIGNED_IN))
    first = await stamp()
    async with maker() as session:
        await session.execute(
            update(CourseAccessRule)
            .where(CourseAccessRule.target_id == course.id)
            .values(updated_at=first - timedelta(days=1))
        )
        await session.commit()
    await restrict(maker, course, AccessRule(Audience.STUDENTS))

    assert await stamp() > first - timedelta(days=1)


async def test_guest_contact_has_no_telegram_but_signed_in_contact_does(
    maker: async_sessionmaker[AsyncSession],
    gated: LearningServices,
    identity: FakeIdentityDirectory,
    student: Actor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Guests see the lead's name only; signed-in users also get the handle."""
    lead = identity.add(first_name="Lola", last_name="Lead")
    course = await seed_course(maker, steps=STEPS, created_by=lead.id)

    async def accounts(user_id: UUID) -> list[TelegramAccountRef]:
        return [TelegramAccountRef(1, user_id, False, "lola", False)]

    monkeypatch.setattr(identity, "telegram_accounts", accounts)
    secret = course.step("s2").step_id
    await restrict(maker, course, chosen(WhenDenied.LOCKED, users=(new_id(),)), secret)

    guest = await gated.public_courses.page(course.slug)
    page = await gated.get_course_page.execute(student, course.slug)
    assert guest.contact is not None and guest.contact.telegram is None
    assert guest.contact.name == "Lola Lead"
    assert page.contact is not None and page.contact.telegram == "lola"


async def test_guest_lesson_of_a_closed_course_looks_missing(
    maker: async_sessionmaker[AsyncSession],
    gated: LearningServices,
    clock: FixedClock,
) -> None:
    """Outside the enrolment window the guest lesson is a 404."""
    course = await seed_course(maker, steps=STEPS)
    async with maker() as session:
        await session.execute(
            update(Course)
            .where(Course.id == course.id)
            .values(enrolment_ends_at=clock.now() - timedelta(days=1))
        )
        await session.commit()

    with pytest.raises(CourseNotFoundError):
        await gated.public_courses.step(course.id, course.step("s1").step_id)
