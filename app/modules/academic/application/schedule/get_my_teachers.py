"""The teachers of a student's groups, with contacts, schedule and status."""

import datetime as dt
from dataclasses import dataclass, field
from uuid import UUID

from app.modules.academic.application.schedule.common import caller_locale, today
from app.modules.academic.application.schedule.ports.reader import ScheduleReader
from app.modules.academic.domain.schedule.audience_display import group_label
from app.modules.academic.domain.schedule.errors import TeacherNotFoundError
from app.modules.academic.domain.schedule.lesson_view import LessonView
from app.modules.academic.domain.schedule.school_days import SCHOOL_DAYS
from app.modules.academic.domain.schedule.teacher_status import current_and_next
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.contracts.identity import IdentityDirectory, TeacherContacts

LOOKAHEAD_DAYS = 14


@dataclass(frozen=True, slots=True)
class TeacherLessonData:
    """One lesson of a teacher, as the student's page shows it."""

    date: dt.date
    weekday: int
    starts_at: dt.datetime
    ends_at: dt.datetime
    subject_id: UUID
    subject: str
    group: str | None
    room: str | None
    lesson_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class TeacherSubjectData:
    """A subject a teacher teaches the student: id and name in the caller's locale."""

    id: UUID
    name: str


@dataclass(frozen=True, slots=True)
class MyTeacherData:
    """A teacher of the student."""

    id: UUID
    first_name: str
    last_name: str
    middle_name: str | None
    photo_url: str | None
    subjects: list[str]
    subject_refs: list[TeacherSubjectData]
    contacts: TeacherContacts
    teaching_now: bool
    current: TeacherLessonData | None
    next: TeacherLessonData | None
    week: list[TeacherLessonData] = field(default_factory=list)
    upcoming: list[TeacherLessonData] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _Window:
    """The moment and the dates a page of teachers covers."""

    now: dt.datetime
    day: dt.date
    monday: dt.date
    sunday: dt.date

    @property
    def last(self) -> dt.date:
        """The last date to load: the end of the week or the lookahead, the later."""
        return max(self.sunday, self.day + dt.timedelta(days=LOOKAHEAD_DAYS))


def _window(clock: Clock) -> _Window:
    day = today(clock)
    monday = day - dt.timedelta(days=day.weekday())
    return _Window(
        now=clock.now(), day=day, monday=monday, sunday=monday + dt.timedelta(days=6)
    )


def _group_label(view: LessonView) -> str | None:
    return group_label(view.ref.audience, view.audience_groups)


def _lesson(view: LessonView) -> TeacherLessonData:
    ref = view.ref
    return TeacherLessonData(
        date=ref.date,
        weekday=ref.date.isoweekday(),
        starts_at=ref.starts_at,
        ends_at=ref.ends_at,
        subject_id=ref.subject_id,
        subject=ref.subject_name,
        group=_group_label(view),
        room=ref.room_name,
        lesson_id=ref.id if view.persisted else None,
    )


def _school_days_only(views: list[LessonView]) -> list[LessonView]:
    return [v for v in views if v.ref.date.isoweekday() in SCHOOL_DAYS]


def _by_teacher(views: list[LessonView]) -> dict[UUID, list[LessonView]]:
    by_teacher: dict[UUID, list[LessonView]] = {}
    for view in _school_days_only(views):
        if view.ref.teacher_id is not None:
            by_teacher.setdefault(view.ref.teacher_id, []).append(view)
    return by_teacher


async def _assemble(
    identity: IdentityDirectory,
    by_teacher: dict[UUID, list[LessonView]],
    window: _Window,
) -> list[MyTeacherData]:
    """Build the teachers that exist, ordered by name; photos in one batch call."""
    users = await identity.get_users(list(by_teacher))
    photos = await identity.photo_urls(list(users))
    result: list[MyTeacherData] = []
    for teacher_id, views in by_teacher.items():
        user = users.get(teacher_id)
        if user is None:
            continue
        prefs = await identity.get_preferences(teacher_id)
        result.append(
            _build(
                user.id,
                user.first_name,
                user.last_name,
                user.middle_name,
                photos.get(teacher_id),
                prefs.contacts,
                views,
                window,
            )
        )
    result.sort(key=lambda t: (t.last_name.lower(), t.first_name.lower()))
    return result


def _build(
    teacher_id: UUID,
    first_name: str,
    last_name: str,
    middle_name: str | None,
    photo_url: str | None,
    contacts: TeacherContacts,
    views: list[LessonView],
    window: _Window,
) -> MyTeacherData:
    by_ref = {id(view.ref): view for view in views}
    current, upcoming = current_and_next((v.ref for v in views), window.now)
    live = [v for v in views if v.ref.status != "cancelled"]

    def in_dates(first: dt.date, last: dt.date) -> list[TeacherLessonData]:
        chosen = sorted(
            (v for v in live if first <= v.ref.date <= last),
            key=lambda v: (v.ref.starts_at, str(v.ref.id)),
        )
        return [_lesson(v) for v in chosen]

    subject_names = {v.ref.subject_id: v.ref.subject_name for v in live}
    subject_refs = sorted(
        (TeacherSubjectData(id=sid, name=name) for sid, name in subject_names.items()),
        key=lambda s: (s.name, str(s.id)),
    )
    return MyTeacherData(
        id=teacher_id,
        first_name=first_name,
        last_name=last_name,
        middle_name=middle_name,
        photo_url=photo_url,
        subjects=sorted(set(subject_names.values())),
        subject_refs=subject_refs,
        contacts=contacts,
        teaching_now=current is not None,
        current=_lesson(by_ref[id(current)]) if current else None,
        next=_lesson(by_ref[id(upcoming)]) if upcoming else None,
        week=in_dates(window.monday, window.sunday),
        upcoming=in_dates(window.day, window.day + dt.timedelta(days=LOOKAHEAD_DAYS)),
    )


class GetMyTeachers:
    """Teachers of the student's groups and subgroups in the current week."""

    def __init__(
        self, reader: ScheduleReader, identity: IdentityDirectory, clock: Clock
    ) -> None:
        """Store the dependencies."""
        self.reader = reader
        self.identity = identity
        self.clock = clock

    async def execute(self, actor: Actor) -> list[MyTeacherData]:
        """Return the teachers ordered by name."""
        window = _window(self.clock)
        locale = await caller_locale(self.identity, actor)
        views = await self.reader.projected_for_student(
            actor.user_id, window.monday, window.last, locale
        )
        return await _assemble(self.identity, _by_teacher(views), window)


class GetMyTeacher:
    """One teacher of the student, the same card as in the list."""

    def __init__(
        self, reader: ScheduleReader, identity: IdentityDirectory, clock: Clock
    ) -> None:
        """Store the dependencies."""
        self.reader = reader
        self.identity = identity
        self.clock = clock

    async def execute(self, actor: Actor, teacher_id: UUID) -> MyTeacherData:
        """Return the teacher or raise TeacherNotFoundError if they do not teach."""
        if not await self.reader.teaches_student(teacher_id, actor.user_id):
            raise TeacherNotFoundError(params={"teacher_id": str(teacher_id)})
        window = _window(self.clock)
        locale = await caller_locale(self.identity, actor)
        views = await self.reader.projected_for_student(
            actor.user_id, window.monday, window.last, locale
        )
        # A teacher without lessons in the window still gets a (quiet) card.
        mine = {teacher_id: _by_teacher(views).get(teacher_id, [])}
        found = await _assemble(self.identity, mine, window)
        if not found:
            raise TeacherNotFoundError(params={"teacher_id": str(teacher_id)})
        return found[0]
