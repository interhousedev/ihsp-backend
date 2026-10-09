"""Database rules of the models, checked on a migrated database (README -> Models)."""

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.modules.academic.infrastructure.orm import (
    Group,
    Lesson,
    Mark,
    Result,
    Room,
    Student,
    Subject,
    Term,
    TimetableEntry,
)
from app.modules.ai.infrastructure.orm import Chat as AiChat
from app.modules.ai.infrastructure.orm import ChatMessage as AiChatMessage
from app.modules.flashcards.infrastructure.orm import (
    Flashcard,
    FlashcardReview,
    FlashcardSet,
)
from app.modules.identity.infrastructure.orm import AuditEvent, Session, User
from app.modules.links.infrastructure.orm import Link
from app.modules.lms.infrastructure.orm import (
    Course,
    CourseStaff,
    CourseStep,
    CourseVersion,
    StepRevision,
    TestAttempt,
)
from app.shared.ids import new_id

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

NOW = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)


@pytest.fixture
async def conn(migrated_engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    """A connection inside a transaction that is rolled back after the test."""
    async with migrated_engine.connect() as connection:
        transaction = await connection.begin()
        yield connection
        await transaction.rollback()


@pytest.fixture
async def db(conn: AsyncConnection) -> AsyncIterator[AsyncSession]:
    """An ORM session on the test transaction (commits become savepoints)."""
    async with AsyncSession(
        bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
    ) as session:
        yield session


async def assert_rejected(db: AsyncSession, *rows: Any) -> None:
    """Flush rows and expect the database to refuse them."""
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add_all(rows)
            await db.flush()


async def saved(db: AsyncSession, *rows: Any) -> None:
    """Flush rows that must be accepted."""
    db.add_all(rows)
    await db.flush()


# - - - Builders - - -


def make_user(**fields: Any) -> User:
    """Build a user row."""
    values: dict[str, Any] = {
        "first_name": "Aleksey",
        "last_name": "Brastilov",
        "status": "active",
        "roles": ["student"],
    }
    return User(**{**values, **fields})


async def make_lesson_parents(db: AsyncSession) -> tuple[Term, Subject]:
    """Create the term and subject every lesson needs."""
    term = Term(
        id=new_id(),
        academic_year="2026-2027",
        half=1,
        starts_on=date(2026, 9, 2),
        ends_on=date(2026, 12, 30),
    )
    subject = Subject(id=new_id(), name={"uz": "Matematika", "ru": "", "en": "Math"})
    await saved(db, term, subject)
    return term, subject


def make_lesson(term: Term, subject: Subject, **fields: Any) -> Lesson:
    """Build a 45-minute lesson at 09:00 on 2026-10-06."""
    values: dict[str, Any] = {
        "id": new_id(),
        "term_id": term.id,
        "date": date(2026, 10, 6),
        "period": 1,
        "starts_at": NOW,
        "ends_at": NOW + timedelta(minutes=45),
        "subject_id": subject.id,
        "audience": [str(new_id())],
    }
    return Lesson(**{**values, **fields})


# - - - id - - -


async def test_user_defaults_and_arrays_round_trip(db: AsyncSession) -> None:
    """Arrays, jsonb and server defaults of id.users work."""
    user = make_user(roles=["teacher", "lms_admin"], login="a.b")
    await saved(db, user)

    await db.refresh(user)

    assert user.roles == ["teacher", "lms_admin"]
    assert user.preferences == {}
    assert user.auth_epoch == 0
    assert user.otp_enabled is False
    assert user.created_at.tzinfo is not None


async def test_user_status_outside_the_enum_is_rejected(db: AsyncSession) -> None:
    """The status enum is enforced by a CHECK constraint."""
    await assert_rejected(db, make_user(status="vanished"))


async def test_recovery_email_is_unique_ignoring_case(db: AsyncSession) -> None:
    """ID: unique on lower(recovery_email)."""
    await saved(db, make_user(recovery_email="Aleksey@Example.uz"))

    await assert_rejected(db, make_user(recovery_email="aleksey@example.uz"))


async def test_login_is_unique(db: AsyncSession) -> None:
    """Two users cannot share a login; several users may have none."""
    await saved(db, make_user(login="x.y"), make_user(), make_user())

    await assert_rejected(db, make_user(login="x.y"))


async def test_session_ip_reads_back_as_a_string(db: AsyncSession) -> None:
    """The inet column is a str on both sides, not an ipaddress object."""
    user = make_user()
    await saved(db, user)
    login = Session(user_id=user.id, ip="10.0.0.5", user_agent="pytest", expires_at=NOW)
    await saved(db, login)

    await db.refresh(login)

    assert login.ip == "10.0.0.5"
    assert login.amr == []


async def test_audit_event_keeps_metadata_and_needs_no_user(db: AsyncSession) -> None:
    """Audit rows have no foreign keys; metadata is the ``meta`` attribute."""
    event = AuditEvent(type="login.failed", user_id=new_id(), meta={"n": 3})
    await saved(db, event)

    await db.refresh(event)

    assert event.meta == {"n": 3}
    assert event.ip is None


# - - - academic - - -


async def test_terms_cannot_overlap(db: AsyncSession) -> None:
    """The exclusion constraint on the date range refuses overlapping terms."""
    await saved(
        db,
        Term(
            academic_year="2026-2027",
            half=1,
            starts_on=date(2026, 9, 2),
            ends_on=date(2026, 12, 30),
        ),
    )

    await assert_rejected(
        db,
        Term(
            academic_year="2026-2027",
            half=2,
            starts_on=date(2026, 12, 30),
            ends_on=date(2027, 5, 30),
        ),
    )


async def test_one_teacher_cannot_have_two_overlapping_scheduled_lessons(
    db: AsyncSession,
) -> None:
    """Exclusion constraint on (teacher_id, time range) where scheduled."""
    term, subject = await make_lesson_parents(db)
    teacher = new_id()
    await saved(db, make_lesson(term, subject, teacher_id=teacher))

    await assert_rejected(
        db,
        make_lesson(
            term,
            subject,
            teacher_id=teacher,
            starts_at=NOW + timedelta(minutes=30),
            ends_at=NOW + timedelta(minutes=75),
        ),
    )


async def test_back_to_back_and_cancelled_lessons_do_not_conflict(
    db: AsyncSession,
) -> None:
    """Adjacent lessons and cancelled lessons never block a teacher."""
    term, subject = await make_lesson_parents(db)
    teacher = new_id()
    await saved(db, make_lesson(term, subject, teacher_id=teacher))

    await saved(
        db,
        make_lesson(
            term,
            subject,
            teacher_id=teacher,
            starts_at=NOW + timedelta(minutes=45),
            ends_at=NOW + timedelta(minutes=90),
        ),
        make_lesson(term, subject, teacher_id=teacher, status="cancelled"),
    )


async def test_two_teacher_needed_lessons_may_overlap(db: AsyncSession) -> None:
    """Lessons without a teacher (NULL) never conflict with each other."""
    term, subject = await make_lesson_parents(db)

    await saved(
        db, make_lesson(term, subject), make_lesson(term, subject, teacher_id=None)
    )


async def test_one_room_cannot_host_two_overlapping_scheduled_lessons(
    db: AsyncSession,
) -> None:
    """Exclusion constraint on (room_id, time range) where scheduled."""
    term, subject = await make_lesson_parents(db)
    room = Room(id=new_id(), slug="102", name="102", pin="483920")
    await saved(db, room)
    await saved(db, make_lesson(term, subject, room_id=room.id))

    await assert_rejected(db, make_lesson(term, subject, room_id=room.id))


async def test_attendance_roster_and_absent_are_set_together(
    db: AsyncSession,
) -> None:
    """(attendance_roster IS NULL) = (attendance_absent IS NULL)."""
    term, subject = await make_lesson_parents(db)
    student = new_id()

    await assert_rejected(db, make_lesson(term, subject, attendance_roster=[student]))


async def test_absent_students_must_belong_to_the_saved_roster(
    db: AsyncSession,
) -> None:
    """attendance_absent <@ attendance_roster."""
    term, subject = await make_lesson_parents(db)
    ours, stranger = new_id(), new_id()

    await assert_rejected(
        db,
        make_lesson(
            term, subject, attendance_roster=[ours], attendance_absent=[stranger]
        ),
    )


async def test_attendance_arrays_round_trip_as_uuids(db: AsyncSession) -> None:
    """uuid[] columns return UUID objects; {} means everyone was present."""
    term, subject = await make_lesson_parents(db)
    first, second = new_id(), new_id()
    lesson = make_lesson(
        term,
        subject,
        attendance_roster=[first, second],
        attendance_absent=[second],
        attendance_excused={str(second): {"by": str(first), "comment": "flu"}},
    )
    await saved(db, lesson)

    await db.refresh(lesson)

    assert lesson.attendance_roster == [first, second]
    assert lesson.attendance_absent == [second]
    assert isinstance(lesson.attendance_roster[0], UUID)
    assert lesson.attendance_version == 0


async def test_a_timetable_entry_generates_a_lesson_once_per_origin_date(
    db: AsyncSession,
) -> None:
    """Unique (timetable_entry_id, origin_date)."""
    term, subject = await make_lesson_parents(db)
    entry = TimetableEntry(
        id=new_id(),
        term_id=term.id,
        weekday=2,
        period=1,
        subject_id=subject.id,
        audience=[str(new_id())],
        valid_from=date(2026, 9, 2),
    )
    await saved(db, entry)
    await saved(
        db,
        make_lesson(
            term,
            subject,
            timetable_entry_id=entry.id,
            origin_date=date(2026, 10, 6),
        ),
    )

    await assert_rejected(
        db,
        make_lesson(
            term,
            subject,
            timetable_entry_id=entry.id,
            origin_date=date(2026, 10, 6),
            starts_at=NOW + timedelta(hours=5),
            ends_at=NOW + timedelta(hours=6),
        ),
    )


async def test_timetable_entry_weekday_is_monday_to_saturday(
    db: AsyncSession,
) -> None:
    """CHECK weekday BETWEEN 1 AND 6."""
    term, subject = await make_lesson_parents(db)

    await assert_rejected(
        db,
        TimetableEntry(
            term_id=term.id,
            weekday=7,
            period=1,
            subject_id=subject.id,
            audience=[str(new_id())],
            valid_from=date(2026, 9, 2),
        ),
    )


async def _student(db: AsyncSession) -> Student:
    """Create a group and a student in it."""
    group = Group(id=new_id(), name="2TN2", slug="2tn2")
    student = Student(user_id=new_id(), group_id=group.id)
    await saved(db, group)
    await saved(db, student)
    return student


async def test_active_group_slugs_are_unique_but_archived_ones_are_free(
    db: AsyncSession,
) -> None:
    """Partial unique index on slug where status = 'active'."""
    await saved(db, Group(name="2TN2", slug="2tn2"))
    await saved(db, Group(name="2TN2", slug="2tn2", status="archived"))

    await assert_rejected(db, Group(name="2TN2", slug="2tn2"))


async def test_student_subgroup_is_one_or_two(db: AsyncSession) -> None:
    """CHECK subgroup IN (1, 2)."""
    student = await _student(db)

    student.subgroup = 3

    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await db.flush()


async def test_marks_identity_is_the_natural_key(db: AsyncSession) -> None:
    """Unique (student, subject, semester, type, date, value, ordinal)."""
    student = await _student(db)
    subject = Subject(id=new_id(), name={"uz": "", "ru": "", "en": "Math"})
    await saved(db, subject)
    fields: dict[str, Any] = {
        "student_id": student.user_id,
        "subject_id": subject.id,
        "semester": 3,
        "type": "lesson",
        "value": 5,
        "date": date(2026, 10, 5),
    }
    await saved(db, Mark(**fields))
    await saved(db, Mark(**fields, ordinal=2))

    await assert_rejected(db, Mark(**fields))


async def test_mark_value_is_between_two_and_five(db: AsyncSession) -> None:
    """CHECK value BETWEEN 2 AND 5."""
    student = await _student(db)
    subject = Subject(id=new_id(), name={"uz": "", "ru": "", "en": "Math"})
    await saved(db, subject)

    await assert_rejected(
        db,
        Mark(
            student_id=student.user_id,
            subject_id=subject.id,
            semester=1,
            type="final",
            value=6,
            date=date(2026, 10, 5),
        ),
    )


async def test_one_gpa_row_per_student_and_semester(db: AsyncSession) -> None:
    """Unique (student, semester, subject) treats NULL subjects as equal."""
    student = await _student(db)
    await saved(
        db, Result(student_id=student.user_id, semester=3, value=Decimal("4.50"))
    )

    await assert_rejected(
        db, Result(student_id=student.user_id, semester=3, value=Decimal("4.00"))
    )


# - - - links - - -


async def test_url_link_needs_a_target_url_and_nothing_else(db: AsyncSession) -> None:
    """kind = 'url' <=> target_url is set."""
    await saved(
        db, Link(slug="7_k", kind="url", owner_id=new_id(), target_url="https://a.uz")
    )

    await assert_rejected(db, Link(slug="8_k", kind="url", owner_id=new_id()))
    await assert_rejected(
        db, Link(slug="9_k", kind="file", owner_id=new_id(), target_url="https://a.uz")
    )


async def test_lesson_resources_have_a_lesson_and_a_role_together(
    db: AsyncSession,
) -> None:
    """(lesson_id IS NULL) = (lesson_role IS NULL); only url and file links."""
    owner, lesson = new_id(), new_id()
    await saved(
        db,
        Link(
            slug="a1",
            kind="url",
            owner_id=owner,
            target_url="https://a.uz",
            lesson_id=lesson,
            lesson_role="material",
        ),
    )

    await assert_rejected(
        db,
        Link(
            slug="a2",
            kind="url",
            owner_id=owner,
            target_url="https://a.uz",
            lesson_id=lesson,
        ),
    )
    await assert_rejected(
        db,
        Link(
            slug="a3",
            kind="chat",
            owner_id=owner,
            target_id=new_id(),
            lesson_id=lesson,
            lesson_role="material",
        ),
    )


async def test_share_mode_is_only_for_chats(db: AsyncSession) -> None:
    """share_mode IS NULL OR kind = 'chat'."""
    owner = new_id()
    await saved(
        db,
        Link(
            slug="c-1",
            kind="chat",
            owner_id=owner,
            target_id=new_id(),
            share_mode="live",
        ),
    )

    await assert_rejected(
        db,
        Link(
            slug="f-1",
            kind="flashcard_set",
            owner_id=owner,
            target_id=new_id(),
            share_mode="live",
        ),
    )


async def test_a_slug_is_free_again_after_it_is_released(db: AsyncSession) -> None:
    """Partial unique index on slug where slug_released_at IS NULL."""
    owner = new_id()
    first = Link(slug="7_k", kind="url", owner_id=owner, target_url="https://a.uz")
    await saved(db, first)
    await assert_rejected(
        db, Link(slug="7_k", kind="url", owner_id=owner, target_url="https://b.uz")
    )

    first.slug_released_at = NOW
    await db.flush()

    await saved(
        db, Link(slug="7_k", kind="url", owner_id=owner, target_url="https://b.uz")
    )
    rows = await db.scalars(select(Link).where(Link.slug == "7_k"))
    assert len(rows.all()) == 2


# - - - flashcards (schema ai) - - -


async def test_flashcard_defaults_match_the_spaced_repetition_start(
    db: AsyncSession,
) -> None:
    """New cards start as state new with ease 2.5; sets get 20 and 200 per day."""
    flashcard_set = FlashcardSet(owner_id=new_id(), title="Limits", source="manual")
    await saved(db, flashcard_set)
    card = Flashcard(set_id=flashcard_set.id, position=1, front="a", back="b")
    await saved(db, card)

    await db.refresh(flashcard_set)
    await db.refresh(card)

    assert (flashcard_set.new_per_day, flashcard_set.reviews_per_day) == (20, 200)
    assert (card.state, card.step, card.ease, card.reps) == ("new", 0, 2.5, 0)


def make_review(flashcard_set: FlashcardSet, card: Flashcard, **fields: Any) -> Any:
    """Build a review log row for a card."""
    values: dict[str, Any] = {
        "user_id": flashcard_set.owner_id,
        "set_id": flashcard_set.id,
        "card_id": card.id,
        "rating": "medium",
        "state_before": "new",
        "interval_after_days": 0.5,
        "reviewed_at": NOW,
    }
    return FlashcardReview(**{**values, **fields})


async def test_a_review_log_row_accepts_the_four_ratings_and_four_states(
    db: AsyncSession,
) -> None:
    """ai.flashcard_reviews: rating and state_before are checked; time is optional."""
    flashcard_set = FlashcardSet(owner_id=new_id(), title="Log", source="manual")
    await saved(db, flashcard_set)
    card = Flashcard(set_id=flashcard_set.id, position=1, front="a", back="b")
    await saved(db, card)

    await saved(
        db,
        *(
            make_review(flashcard_set, card, rating=r)
            for r in ("again", "hard", "medium", "easy")
        ),
        *(
            make_review(flashcard_set, card, state_before=s)
            for s in ("new", "learning", "review", "relearning")
        ),
    )
    await assert_rejected(db, make_review(flashcard_set, card, rating="good"))
    await assert_rejected(db, make_review(flashcard_set, card, state_before="old"))
    row = make_review(flashcard_set, card)
    await saved(db, row)
    await db.refresh(row)

    assert row.duration_ms is None


async def test_deleting_a_card_keeps_its_log_and_deleting_the_set_removes_it(
    db: AsyncSession,
) -> None:
    """ai.flashcard_reviews: card_id is set to NULL, set_id cascades."""
    flashcard_set = FlashcardSet(owner_id=new_id(), title="Log", source="manual")
    await saved(db, flashcard_set)
    card = Flashcard(set_id=flashcard_set.id, position=1, front="a", back="b")
    await saved(db, card)
    row = make_review(flashcard_set, card)
    await saved(db, row)

    await db.delete(card)
    await db.flush()
    await db.refresh(row)
    assert row.card_id is None

    await db.delete(flashcard_set)
    await db.flush()
    remaining = await db.scalars(select(FlashcardReview))
    assert remaining.all() == []


# - - - ai chats (schema ai) - - -


async def test_a_chat_tier_is_fast_by_default_and_checked(db: AsyncSession) -> None:
    """ai.chats: tier defaults to fast and accepts only fast or smart."""
    plain = AiChat(owner_id=new_id(), assistant="student", title="T", model="m")
    await saved(
        db,
        plain,
        AiChat(
            owner_id=new_id(), assistant="student", title="T", model="m", tier="smart"
        ),
    )
    await db.refresh(plain)

    assert plain.tier == "fast"
    await assert_rejected(
        db,
        AiChat(
            owner_id=new_id(), assistant="student", title="T", model="m", tier="turbo"
        ),
    )


async def test_message_feedback_is_checked(db: AsyncSession) -> None:
    """ai.chat_messages: feedback is 1 or -1; a comment needs a rating (max 500)."""
    chat = AiChat(owner_id=new_id(), assistant="student", title="T", model="m")
    await saved(db, chat)

    def message(seq: int, **fields: Any) -> AiChatMessage:
        return AiChatMessage(
            chat_id=chat.id, seq=seq, role="assistant", content={"text": "a"}, **fields
        )

    await saved(
        db,
        message(1),
        message(2, feedback=1),
        message(3, feedback=-1, feedback_comment="x" * 500),
    )
    await assert_rejected(db, message(4, feedback=0))
    await assert_rejected(db, message(5, feedback=2))
    await assert_rejected(db, message(6, feedback_comment="no rating"))
    await assert_rejected(db, message(7, feedback=1, feedback_comment="x" * 501))


# - - - lms - - -


async def _course(db: AsyncSession) -> Course:
    """Create a course with the required hashes."""
    course = Course(
        id=new_id(),
        slug=f"c-{new_id()}",
        title="Derivatives",
        visibility="public",
        created_by=new_id(),
        draft_meta={"title": "Derivatives", "description": ""},
        outline_hash="0" * 64,
    )
    await saved(db, course)
    return course


async def test_live_pointers_close_the_course_version_and_step_revision_cycles(
    db: AsyncSession,
) -> None:
    """courses.live_version_id and course_steps.live_revision_id are real FKs."""
    course = await _course(db)
    author = new_id()
    version = CourseVersion(
        course_id=course.id,
        number=1,
        meta={},
        outline={"sections": []},
        changes={},
        published_by=author,
    )
    step = CourseStep(
        course_id=course.id, draft={"title": "t", "blocks": []}, draft_hash="a" * 64
    )
    await saved(db, version, step)
    revision = StepRevision(
        step_id=step.id,
        content={"title": "t", "blocks": []},
        content_hash="a" * 64,
        kind="publish",
        created_by=author,
    )
    await saved(db, revision)

    course.live_version_id = version.id
    step.live_revision_id = revision.id
    await db.flush()
    await db.refresh(course)

    assert course.live_version_id == version.id
    assert course.draft_outline == {"sections": []}
    assert (course.lock_version, course.draft_seq) == (0, 0)


async def test_live_version_must_exist(db: AsyncSession) -> None:
    """The circular foreign key is enforced."""
    course = await _course(db)

    course.live_version_id = new_id()

    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await db.flush()


async def test_a_step_with_revisions_cannot_be_deleted(db: AsyncSession) -> None:
    """step_revisions.step_id is a RESTRICT foreign key."""
    course = await _course(db)
    step = CourseStep(
        course_id=course.id, draft={"title": "t", "blocks": []}, draft_hash="a" * 64
    )
    await saved(db, step)
    await saved(
        db,
        StepRevision(
            step_id=step.id,
            content={},
            content_hash="b" * 64,
            kind="checkpoint",
            created_by=new_id(),
        ),
    )

    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await db.delete(step)
            await db.flush()


async def test_revision_content_is_unique_per_step(db: AsyncSession) -> None:
    """Unique (step_id, content_hash): equal content reuses the revision."""
    course = await _course(db)
    step = CourseStep(
        course_id=course.id, draft={"title": "t", "blocks": []}, draft_hash="a" * 64
    )
    await saved(db, step)
    fields: dict[str, Any] = {
        "step_id": step.id,
        "content": {},
        "content_hash": "c" * 64,
        "kind": "publish",
        "created_by": new_id(),
    }
    await saved(db, StepRevision(**fields))

    await assert_rejected(db, StepRevision(**fields))


async def test_course_staff_permissions_are_limited_to_the_known_five(
    db: AsyncSession,
) -> None:
    """CHECK permissions <@ the allowed set."""
    course = await _course(db)
    await saved(
        db,
        CourseStaff(
            course_id=course.id,
            user_id=new_id(),
            role="Teacher",
            permissions=["edit", "publish"],
            added_by=new_id(),
        ),
    )

    await assert_rejected(
        db,
        CourseStaff(
            course_id=course.id,
            user_id=new_id(),
            role="Hacker",
            permissions=["root"],
            added_by=new_id(),
        ),
    )


async def test_attempt_numbers_are_unique_but_previews_are_not_counted(
    db: AsyncSession,
) -> None:
    """Unique (user, step, block, attempt_no) where not is_preview."""
    course = await _course(db)
    author = new_id()
    step = CourseStep(
        course_id=course.id, draft={"title": "t", "blocks": []}, draft_hash="a" * 64
    )
    await saved(db, step)
    revision = StepRevision(
        step_id=step.id,
        content={},
        content_hash="d" * 64,
        kind="publish",
        created_by=author,
    )
    await saved(db, revision)
    student = new_id()
    fields: dict[str, Any] = {
        "user_id": student,
        "step_id": step.id,
        "revision_id": revision.id,
        "block_id": "b91cWm4r",
        "attempt_no": 1,
        "variant": {"question_ids": [], "option_order": {}},
        "max_score": 5,
    }
    await saved(db, TestAttempt(**fields), TestAttempt(**fields, is_preview=True))
    await saved(db, TestAttempt(**fields, is_preview=True))

    await assert_rejected(db, TestAttempt(**fields))
