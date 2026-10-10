"""The teachers of a student's groups, with contacts, schedule and status."""

import datetime as dt
from dataclasses import dataclass, field
from uuid import UUID

from app.modules.academic.application.schedule.common import caller_locale, today
from app.modules.academic.application.schedule.ports.reader import ScheduleReader
from app.modules.academic.domain.schedule.audience_display import display_names
from app.modules.academic.domain.schedule.lesson_view import LessonView
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
    subject: str
    group: str | None
    room: str | None


@dataclass(frozen=True, slots=True)
class MyTeacherData:
    """A teacher of the student."""

    id: UUID
    first_name: str
    last_name: str
    middle_name: str | None
    subjects: list[str]
    contacts: TeacherContacts
    teaching_now: bool
    current: TeacherLessonData | None
    next: TeacherLessonData | None
    week: list[TeacherLessonData] = field(default_factory=list)


def _group_label(view: LessonView) -> str | None:
    labels = display_names(view.ref.audience, view.audience_groups)
    return ", ".join(labels) or None


def _lesson(view: LessonView) -> TeacherLessonData:
    ref = view.ref
    return TeacherLessonData(
        date=ref.date,
        weekday=ref.date.isoweekday(),
        starts_at=ref.starts_at,
        ends_at=ref.ends_at,
        subject=ref.subject_name,
        group=_group_label(view),
        room=ref.room_name,
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
        now = self.clock.now()
        day = today(self.clock)
        monday = day - dt.timedelta(days=day.weekday())
        sunday = monday + dt.timedelta(days=6)
        last = max(sunday, day + dt.timedelta(days=LOOKAHEAD_DAYS))
        locale = await caller_locale(self.identity, actor)
        views = await self.reader.projected_for_student(
            actor.user_id, monday, last, locale
        )
        by_teacher: dict[UUID, list[LessonView]] = {}
        for view in views:
            if view.ref.teacher_id is not None:
                by_teacher.setdefault(view.ref.teacher_id, []).append(view)
        users = await self.identity.get_users(list(by_teacher))
        result: list[MyTeacherData] = []
        for teacher_id, teacher_views in by_teacher.items():
            user = users.get(teacher_id)
            if user is None:
                continue
            prefs = await self.identity.get_preferences(teacher_id)
            result.append(
                self._build(
                    user.id,
                    user.first_name,
                    user.last_name,
                    user.middle_name,
                    prefs.contacts,
                    teacher_views,
                    now,
                    (monday, sunday),
                )
            )
        result.sort(key=lambda t: (t.last_name.lower(), t.first_name.lower()))
        return result

    @staticmethod
    def _build(
        teacher_id: UUID,
        first_name: str,
        last_name: str,
        middle_name: str | None,
        contacts: TeacherContacts,
        views: list[LessonView],
        now: dt.datetime,
        week: tuple[dt.date, dt.date],
    ) -> MyTeacherData:
        by_ref = {id(view.ref): view for view in views}
        current, upcoming = current_and_next((v.ref for v in views), now)
        live = [v for v in views if v.ref.status != "cancelled"]
        in_week = sorted(
            (v for v in live if week[0] <= v.ref.date <= week[1]),
            key=lambda v: v.ref.starts_at,
        )
        subjects = sorted({v.ref.subject_name for v in live})
        return MyTeacherData(
            id=teacher_id,
            first_name=first_name,
            last_name=last_name,
            middle_name=middle_name,
            subjects=subjects,
            contacts=contacts,
            teaching_now=current is not None,
            current=_lesson(by_ref[id(current)]) if current else None,
            next=_lesson(by_ref[id(upcoming)]) if upcoming else None,
            week=[_lesson(v) for v in in_week],
        )
