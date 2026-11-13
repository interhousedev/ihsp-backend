"""Made-up school data around the review accounts (idempotent, never touches others).

Everything here belongs to the "Review group", the three review users, three review
subjects, one review course and one review flash card set. A rerun finds each piece
and leaves it as it is; nothing is read from or written to EMIS.
"""

import datetime as dt
import hashlib
from dataclasses import dataclass
from uuid import UUID

from app.bootstrap.container import Container
from app.bootstrap.seed.content import CARDS, LESSON_TEXT, QUESTIONS
from app.interfaces.mcp.lms.blocks import (
    build_flashcards_block,
    build_test_block,
    build_text_block,
)
from app.modules.academic.application.assessments.inputs import (
    AssessmentInput,
    StaffFilters,
)
from app.modules.academic.application.schedule.entry_builder import EntryInput
from app.modules.academic.application.schedule.results import TermData
from app.modules.academic.domain import audience as audience_keys
from app.modules.academic.domain.marks.sync import (
    FetchedRatings,
    StudentSyncState,
    SyncSubject,
)
from app.modules.academic.domain.schedule.student import Student
from app.modules.academic.domain.schedule.subject import Subject
from app.modules.lms.domain.authoring.enums import Visibility
from app.modules.lms.domain.authoring.errors import SlugTakenError
from app.shared.actor import SYSTEM_ACTOR, Actor, Role
from app.shared.base_error import ConflictError
from app.shared.clock import local_today
from app.shared.contracts.academic import LessonRef
from app.shared.contracts.emis import EmisMark, EmisMarkType, EmisSubjectRatings

import structlog

log = structlog.get_logger(__name__)

GROUP_NAME = "Review group"
FLASHCARD_SET_TITLE = "Review: derivatives"
COURSE_TITLE = "Review course: Derivatives"
COURSE_SLUG = "review-derivatives"
HOMEWORK_TEXT = "Review exercise: solve problems 1 to 5 and bring the answers."
QUIZ_TITLE = "Review quiz"
LESSONS_BEHIND_DAYS = 28
LESSONS_AHEAD_DAYS = 14
LESSON_MARKS = (4, 5, 3, 5)
ABSENT_LESSONS = 1

SUBJECTS: tuple[dict[str, str], ...] = (
    {"en": "Mathematics", "ru": "Математика", "uz": "Matematika"},
    {"en": "English", "ru": "Английский язык", "uz": "Ingliz tili"},
    {"en": "Physics", "ru": "Физика", "uz": "Fizika"},
)
# Three periods on each school day, Monday to Friday, subjects in turn.
WEEKDAYS = range(1, 6)
PERIODS = range(1, 4)


@dataclass(frozen=True, slots=True)
class ReviewWorld:
    """Ids of the review accounts and the pieces built around them."""

    student_id: UUID
    teacher_id: UUID
    lms_id: UUID
    group_id: UUID
    subjects: tuple[Subject, ...]
    term: TermData


async def _ensure_group(container: Container, student_id: UUID) -> UUID:
    schedule = container.academic.schedule
    uow = schedule.enrollment.uow_factory()
    async with uow:
        found = next(
            (
                group
                for group in await uow.groups.list_all()
                if group.name.casefold() == GROUP_NAME.casefold()
                and group.status == "active"
            ),
            None,
        )
    if found is not None:
        group_id = found.id
    else:
        group_id = (
            await schedule.create_group.execute(
                name=GROUP_NAME, emis_group_id=None, current_semester=1
            )
        ).id
    async with schedule.enrollment.uow_factory() as uow:
        student = await uow.students.get(student_id)
        if student is None:
            await uow.students.add(Student(user_id=student_id, group_id=group_id))
        elif student.group_id != group_id or student.status != "active":
            student.group_id = group_id
            student.status = "active"
            student.left_at = None
            student.left_reason = None
            await uow.students.save(student)
        await uow.commit()
    return group_id


async def _ensure_subjects(container: Container, group_id: UUID) -> tuple[Subject, ...]:
    schedule = container.academic.schedule
    known = await schedule.list_subjects.execute(None)
    subjects: list[Subject] = []
    for names in SUBJECTS:
        subject = next(
            (
                s
                for s in known
                if s.name.get("en", "").casefold() == names["en"].casefold()
            ),
            None,
        )
        if subject is None:
            subject = await schedule.create_subject.execute(name=names)
        subjects.append(subject)
    async with schedule.enrollment.uow_factory() as uow:
        group = await uow.groups.get(group_id)
        if group is not None:
            missing = [s.id for s in subjects if s.id not in group.subject_ids]
            if missing:
                group.subject_ids = [*group.subject_ids, *missing]
                await uow.groups.save(group)
                await uow.commit()
    return tuple(subjects)


async def _ensure_timetable(container: Container, world: ReviewWorld) -> None:
    schedule = container.academic.schedule
    existing = await schedule.list_entries.execute(
        SYSTEM_ACTOR, term_id=world.term.id, group_id=world.group_id
    )
    if existing:
        return
    created = 0
    slot = 0
    for day in WEEKDAYS:
        for period in PERIODS:
            subject = world.subjects[(slot + day) % len(world.subjects)]
            slot += 1
            try:
                await schedule.create_entry.execute(
                    SYSTEM_ACTOR,
                    EntryInput(
                        term_id=world.term.id,
                        weekday=day,
                        period=period,
                        week_parity="every",
                        subject_id=subject.id,
                        teacher_id=world.teacher_id,
                        room_name=None,
                        audience=[(world.group_id, None)],
                        valid_from=world.term.starts_on,
                        valid_to=None,
                    ),
                )
                created += 1
            except ConflictError:
                log.warning("seed_review_entry_conflict", day=day, period=period)
    log.info("seed_review_timetable", entries=created)


async def _generate_lessons(
    container: Container, world: ReviewWorld, today: dt.date
) -> None:
    term = world.term
    first = max(term.starts_on, today - dt.timedelta(days=LESSONS_BEHIND_DAYS))
    last = min(term.ends_on, today + dt.timedelta(days=LESSONS_AHEAD_DAYS))
    if last < first:
        return
    await container.academic.schedule.generate_lessons.execute(
        term_id=term.id,
        from_date=first,
        days=(last - first).days + 1,
        audience=[audience_keys.key(world.group_id, None)],
    )


def _payload_hash(subject_id: UUID, marks: tuple[EmisMark, ...]) -> str:
    text = "|".join(f"{m.type}:{m.date}:{m.value}" for m in marks)
    return hashlib.sha256(f"review:{subject_id}:{text}".encode()).hexdigest()


async def _seed_marks(
    container: Container,
    world: ReviewWorld,
    lessons: list[LessonRef],
    today: dt.date,
) -> None:
    """A few lesson marks per subject, on the student's past lessons."""
    sync_subjects = tuple(
        SyncSubject(s.id, s.emis_subject_id or 0, s.name) for s in world.subjects
    )
    fetched: list[FetchedRatings] = []
    for sync_subject in sync_subjects:
        dates = sorted(
            {
                lesson.date
                for lesson in lessons
                if lesson.subject_id == sync_subject.subject_id
                and lesson.date < today
                and lesson.status == "scheduled"
            }
        )[: len(LESSON_MARKS)]
        marks = tuple(
            EmisMark(EmisMarkType.LESSON, date, LESSON_MARKS[index])
            for index, date in enumerate(dates)
        )
        fetched.append(
            FetchedRatings(
                sync_subject,
                EmisSubjectRatings(
                    emis_subject_id=sync_subject.emis_subject_id,
                    semester=1,
                    semester_rating=None,
                    marks=marks,
                    payload_hash=_payload_hash(sync_subject.subject_id, marks),
                ),
            )
        )
    state = StudentSyncState(
        user_id=world.student_id,
        group_id=world.group_id,
        subgroup=None,
        status="active",
        backfilled_at=None,
        current_semester=1,
        subjects=sync_subjects,
    )
    marks_services = container.academic.marks
    async with marks_services.uow_factory() as uow:
        await marks_services.apply_ratings.execute(uow, state, fetched, locale="en")
        await uow.commit()


async def _seed_classwork(
    container: Container,
    world: ReviewWorld,
    teacher: Actor,
    today: dt.date,
) -> None:
    """Attendance for the first past lessons, homework for the next ones."""
    classwork = container.academic.classwork
    queries = container.academic.schedule.queries
    start = today - dt.timedelta(days=LESSONS_BEHIND_DAYS)
    end = today + dt.timedelta(days=LESSONS_AHEAD_DAYS)
    lessons = sorted(
        await queries.lessons_for_teacher(world.teacher_id, start, end),
        key=lambda lesson: lesson.starts_at,
    )
    past = [x for x in lessons if x.date < today and x.status == "scheduled"]
    for index, lesson in enumerate(past[-3:]):
        absent = [world.student_id] if index < ABSENT_LESSONS else []
        try:
            await classwork.submit_attendance.execute(
                lesson_id=lesson.id,
                actor=teacher,
                absent=absent,
                base_version=0,
                source="staff",
            )
        except ConflictError:
            continue  # already submitted by an earlier run
    future = [x for x in lessons if x.date >= today and x.status == "scheduled"]
    for lesson in future[:2]:
        if lesson.homework_text:
            continue
        await classwork.set_homework.execute(lesson.id, teacher, HOMEWORK_TEXT, None)


async def _seed_assessment(
    container: Container, world: ReviewWorld, teacher: Actor, today: dt.date
) -> None:
    """One upcoming quiz for the group (once)."""
    assessments = container.academic.assessments
    found = await assessments.list_staff.execute(
        teacher, StaffFilters(group_id=world.group_id, kind="other")
    )
    if any(item.get("title") == QUIZ_TITLE for item in found):
        return
    day = today + dt.timedelta(days=7)
    while day.weekday() > 4:
        day += dt.timedelta(days=1)
    if day > world.term.ends_on:
        return
    await assessments.create.execute(
        teacher,
        AssessmentInput(
            subject_id=world.subjects[0].id,
            audience=[(world.group_id, None)],
            kind="other",
            date=day,
            title=QUIZ_TITLE,
        ),
    )


async def _seed_flashcards(container: Container, student_id: UUID) -> None:
    api = container.flashcards.public
    if any(s["title"] == FLASHCARD_SET_TITLE for s in await api.list_sets(student_id)):
        return
    await api.create_set(
        student_id,
        FLASHCARD_SET_TITLE,
        [(card.front, card.back) for card in CARDS],
        source="manual",
    )


async def _seed_course(container: Container, world: ReviewWorld) -> None:
    """Publish the review course, enrol the student and open its first step."""
    authoring = container.lms.authoring
    creator = Actor(
        user_id=world.lms_id, roles=frozenset({Role.LMS_CREATOR, Role.TEACHER})
    )
    try:
        course = await authoring.create_course.execute(
            creator,
            title=COURSE_TITLE,
            slug=COURSE_SLUG,
            visibility=Visibility.PUBLIC,
        )
    except SlugTakenError:
        course = None
    if course is not None:
        commands = authoring.draft_commands
        section = await commands.create_section(
            creator, course.id, "Basics", via_mcp=False
        )
        blocks = [
            ("What is a derivative", build_text_block(LESSON_TEXT)),
            ("Check yourself", build_test_block(None, QUESTIONS)),
            ("Flash cards", build_flashcards_block(CARDS)),
        ]
        for title, block in blocks:
            step = await commands.create_step(
                creator, course.id, section["id"], title, via_mcp=False
            )
            await commands.add_block(
                creator, UUID(step["step_id"]), block, via_mcp=False
            )
        draft = await authoring.get_course_draft.execute(creator, course.id)
        await authoring.publish_course.execute(
            creator, course.id, draft_seq=draft.draft_seq, note="First version"
        )
    learning = container.lms.learning
    student = Actor(user_id=world.student_id, roles=frozenset({Role.STUDENT}))
    page = await learning.get_course_page.execute(student, COURSE_SLUG)
    # Enrol straight in the store: the use case also provisions an AI notebook.
    async with learning.enroll_in_course.uow_factory() as uow:
        if await uow.enrollments.get(page.id, world.student_id) is None:
            await uow.enrollments.add(
                course_id=page.id, user_id=world.student_id, via="self"
            )
            await uow.commit()
    for section_view in page.outline:
        for step_view in section_view.steps[:1]:
            await learning.mark_step_viewed.execute(student, step_view.step_id)
    log.info("seed_review_course", slug=COURSE_SLUG)


async def seed_review_data(container: Container, ids: dict[str, UUID]) -> ReviewWorld:
    """Build the made-up data of the review accounts; safe to run again."""
    schedule = container.academic.schedule
    term = await schedule.current_term.execute()
    if term is None:
        raise RuntimeError(
            "There is no current term: create one (or run seed-demo) first."
        )
    today = local_today(container.clock)
    group_id = await _ensure_group(container, ids["student"])
    subjects = await _ensure_subjects(container, group_id)
    world = ReviewWorld(
        student_id=ids["student"],
        teacher_id=ids["teacher"],
        lms_id=ids["lms"],
        group_id=group_id,
        subjects=subjects,
        term=term,
    )
    teacher = Actor(user_id=world.teacher_id, roles=frozenset({Role.TEACHER}))
    await _ensure_timetable(container, world)
    await _generate_lessons(container, world, today)
    student_lessons = await schedule.queries.lessons_for_student(
        world.student_id, today - dt.timedelta(days=LESSONS_BEHIND_DAYS), today
    )
    await _seed_marks(container, world, student_lessons, today)
    await _seed_classwork(container, world, teacher, today)
    await _seed_assessment(container, world, teacher, today)
    await _seed_flashcards(container, world.student_id)
    await _seed_course(container, world)
    return world
