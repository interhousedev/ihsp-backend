"""In-memory ScheduleReader over the fake store (same behaviour as the SQL reader)."""

import datetime as dt
import uuid
from collections.abc import Callable, Sequence
from typing import Any
from uuid import UUID

from app.modules.academic.application.schedule.ports.reader import (
    LessonFilters,
    LessonPage,
)
from app.modules.academic.domain import audience as audience_keys
from app.modules.academic.domain.schedule.audience_display import display_names
from app.modules.academic.domain.schedule.generation import expand_entries
from app.modules.academic.domain.schedule.lesson import Lesson
from app.modules.academic.domain.schedule.lesson_view import LessonView
from app.modules.academic.domain.schedule.subject import LANGUAGES, subject_name
from app.shared.contracts.academic import LessonRef, RoomRef, StudentRef
from app.shared.lesson_kind import topic_source_of
from tests.fakes.academic.schedule.store import ScheduleStore, on_a_saturday


class FakeScheduleReader:
    """Reads lessons, rooms and students from the store."""

    def __init__(self, store: ScheduleStore) -> None:
        """Bind to the store."""
        self.store = store

    # - - - views - - -

    def _names(self, audiences: Sequence[Sequence[str]]) -> dict[UUID, str]:
        ids = {g for keys in audiences for g in audience_keys.group_ids(keys)}
        return {g: self.store.groups[g].name for g in ids if g in self.store.groups}

    def _view(self, lesson: Lesson, locale: str) -> LessonView:
        subject = self.store.subjects[lesson.subject_id]
        room = self.store.rooms.get(lesson.room_id) if lesson.room_id else None
        names = self._names([lesson.audience])
        keys = tuple(lesson.audience)
        ref = LessonRef(
            id=lesson.id,
            date=lesson.date,
            period=lesson.period,
            starts_at=lesson.starts_at,
            ends_at=lesson.ends_at,
            subject_id=lesson.subject_id,
            subject_name=subject_name(subject, locale),
            teacher_id=lesson.teacher_id,
            room_id=lesson.room_id,
            room_slug=room.slug if room else None,
            room_name=room.name if room else None,
            audience=keys,
            group_names=display_names(keys, names),
            status=lesson.status,
            topic=lesson.topic,
            homework_text=None,
            homework_due_date=None,
            kind=lesson.kind,
            topic_source=topic_source_of(lesson.topic, lesson.emis_topic),
        )
        return LessonView(
            ref=ref,
            subject_short=subject.short_name,
            is_overridden=lesson.is_overridden,
            changes=dict(lesson.changes) if lesson.changes else None,
            attendance_submitted=False,
            term_id=lesson.term_id,
            audience_groups=names,
        )

    def _views(self, lessons: list[Lesson], locale: str) -> list[LessonView]:
        ordered = sorted(lessons, key=lambda x: (x.date, x.starts_at, str(x.id)))
        return [self._view(lesson, locale) for lesson in ordered]

    def _keys(self, user_id: UUID) -> list[str] | None:
        student = self.store.students.get(user_id)
        if student is None:
            return None
        return audience_keys.student_keys(student.group_id, student.subgroup)

    # - - - students and rooms - - -

    async def student_ref(self, user_id: UUID) -> StudentRef | None:
        """Return the student with the group name."""
        student = self.store.students.get(user_id)
        if student is None:
            return None
        return StudentRef(
            user_id=student.user_id,
            group_id=student.group_id,
            group_name=self.store.groups[student.group_id].name,
            subgroup=student.subgroup,
            status=student.status,
            synced_at=student.synced_at,
        )

    async def subject_title(self, subject_id: UUID, locale: str) -> str | None:
        """The subject's name in the locale, None when it does not exist."""
        subject = self.store.subjects.get(subject_id)
        return None if subject is None else subject_name(subject, locale)

    async def room_by_slug(self, slug: str) -> RoomRef | None:
        """Return the room with the slug."""
        for room in self.store.rooms.values():
            if room.slug == slug:
                return RoomRef(room.id, room.slug, room.name, room.pin, room.status)
        return None

    async def group_user_ids(
        self, group_ids: Sequence[UUID], semesters: Sequence[int]
    ) -> list[UUID]:
        """Return user ids of active students of the groups and semesters."""
        if not group_ids and not semesters:
            return []
        found = []
        for student in self.store.students.values():
            group = self.store.groups.get(student.group_id)
            if group is None or (group_ids and student.group_id not in group_ids):
                continue
            if student.status != "active":
                continue
            if semesters and group.current_semester not in semesters:
                continue
            found.append(student.user_id)
        return found

    async def curated_group_ids(self, teacher_id: UUID) -> list[UUID]:
        """Return active groups the teacher curates."""
        return [
            g.id
            for g in self.store.groups.values()
            if g.curator_id == teacher_id and g.status == "active"
        ]

    # - - - lessons - - -

    async def lesson_view(self, lesson_id: UUID, locale: str) -> LessonView | None:
        """Return one lesson."""
        lesson = self.store.lessons.get(lesson_id)
        if lesson is None or on_a_saturday(lesson.date):
            return None
        return self._view(lesson, locale)

    async def lessons_for_student(
        self, user_id: UUID, start: dt.date, end: dt.date, locale: str
    ) -> list[LessonView]:
        """Return the student's lessons between two dates."""
        keys = self._keys(user_id)
        if keys is None:
            return []
        return self._views(
            [
                lesson
                for lesson in self.store.lessons.values()
                if start <= lesson.date <= end
                and not on_a_saturday(lesson.date)
                and set(lesson.audience) & set(keys)
            ],
            locale,
        )

    async def lessons_for_teacher(
        self, teacher_id: UUID, start: dt.date, end: dt.date, locale: str
    ) -> list[LessonView]:
        """Return the teacher's lessons between two dates."""
        return self._views(
            [
                lesson
                for lesson in self.store.lessons.values()
                if lesson.teacher_id == teacher_id
                and start <= lesson.date <= end
                and not on_a_saturday(lesson.date)
            ],
            locale,
        )

    async def control_lessons(
        self,
        group_ids: Sequence[UUID],
        start: dt.date,
        end: dt.date,
        locale: str,
    ) -> list[LessonView]:
        """Return scheduled midterm and final lessons of the groups."""
        keys = {
            key
            for group_id in group_ids
            for key in audience_keys.student_keys(group_id, None)
        }
        return self._views(
            [
                lesson
                for lesson in self.store.lessons.values()
                if lesson.kind in ("midterm", "final")
                and lesson.status == "scheduled"
                and start <= lesson.date <= end
                and not on_a_saturday(lesson.date)
                and keys & set(lesson.audience)
            ],
            locale,
        )

    async def projected_for_student(
        self, user_id: UUID, start: dt.date, end: dt.date, locale: str
    ) -> list[LessonView]:
        """Return generated lessons and lessons projected from entries."""
        keys = self._keys(user_id)
        if keys is None:
            return []
        generated = await self.lessons_for_student(user_id, start, end, locale)
        projected = self._project(
            lambda entry: bool(set(entry.audience) & set(keys)), start, end, locale
        )
        merged = [*generated, *projected]
        merged.sort(key=lambda view: (view.ref.starts_at, str(view.ref.id)))
        return merged

    async def student_placement(self, user_id: UUID) -> tuple[UUID, int | None] | None:
        """Return (group id, subgroup) of the student, None for an unknown one."""
        student = self.store.students.get(user_id)
        return None if student is None else (student.group_id, student.subgroup)

    async def projected_for_group(
        self, group_id: UUID, start: dt.date, end: dt.date, locale: str
    ) -> list[LessonView]:
        """Return the lessons of the whole group and of both its subgroups."""
        keys = set(audience_keys.student_keys(group_id, None))
        generated = self._views(
            [
                lesson
                for lesson in self.store.lessons.values()
                if start <= lesson.date <= end
                and not on_a_saturday(lesson.date)
                and set(lesson.audience) & keys
            ],
            locale,
        )
        projected = self._project(
            lambda entry: bool(set(entry.audience) & keys), start, end, locale
        )
        merged = [*generated, *projected]
        merged.sort(key=lambda view: (view.ref.starts_at, str(view.ref.id)))
        return merged

    async def projected_for_teacher(
        self, teacher_id: UUID, start: dt.date, end: dt.date, locale: str
    ) -> list[LessonView]:
        """Return the teacher's generated and projected lessons of every group."""
        generated = await self.lessons_for_teacher(teacher_id, start, end, locale)
        projected = self._project(
            lambda entry: entry.teacher_id == teacher_id, start, end, locale
        )
        merged = [*generated, *projected]
        merged.sort(key=lambda view: (view.ref.starts_at, str(view.ref.id)))
        return merged

    async def teaches_student(self, teacher_id: UUID, user_id: UUID) -> bool:
        """Return True if a lesson or entry of the teacher reaches the student."""
        student = self.store.students.get(user_id)
        if student is None or student.status != "active":
            return False
        keys = set(audience_keys.student_keys(student.group_id, student.subgroup))
        audiences = [
            *(
                x.audience
                for x in self.store.lessons.values()
                if x.teacher_id == teacher_id
            ),
            *(
                x.audience
                for x in self.store.entries.values()
                if x.teacher_id == teacher_id
            ),
        ]
        return any(keys & set(audience) for audience in audiences)

    async def student_keys(self, user_id: UUID) -> list[str] | None:
        """Return the audience keys of the student, None for an unknown student."""
        return self._keys(user_id)

    def _project(
        self, wanted: Callable[[Any], bool], start: dt.date, end: dt.date, locale: str
    ) -> list[LessonView]:
        """Project the wanted entries past the last generated lesson of each term."""
        projected: list[LessonView] = []
        for term in self.store.terms.values():
            if term.starts_on > end or term.ends_on < start:
                continue
            dates = [
                lesson.date
                for lesson in self.store.lessons.values()
                if lesson.term_id == term.id and lesson.timetable_entry_id is not None
            ]
            first = max(start, max(dates) + dt.timedelta(days=1)) if dates else start
            entries = [
                e
                for e in self.store.entries.values()
                if e.term_id == term.id and wanted(e)
            ]
            for planned in expand_entries(term, entries, first, end).planned.values():
                projected.append(self._projected(planned, locale))
        return projected

    def _projected(self, planned: Any, locale: str) -> LessonView:
        lesson = Lesson(
            id=uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"{planned.entry_id}:{planned.origin_date.isoformat()}",
            ),
            term_id=planned.term_id,
            date=planned.origin_date,
            period=planned.period,
            starts_at=planned.starts_at,
            ends_at=planned.ends_at,
            subject_id=planned.subject_id,
            teacher_id=planned.teacher_id,
            room_id=planned.room_id,
            audience=list(planned.audience),
        )
        return self._view(lesson, locale)

    async def is_in_audience(self, user_id: UUID, lesson_id: UUID) -> bool:
        """Return True if the active student attends the lesson."""
        student = self.store.students.get(user_id)
        lesson = self.store.lessons.get(lesson_id)
        if student is None or lesson is None or student.status != "active":
            return False
        keys = audience_keys.student_keys(student.group_id, student.subgroup)
        return bool(set(lesson.audience) & set(keys))

    async def is_lesson_teacher(self, user_id: UUID, lesson_id: UUID) -> bool:
        """Return True if the user teaches the lesson."""
        lesson = self.store.lessons.get(lesson_id)
        return lesson is not None and lesson.teacher_id == user_id

    async def head_student_ids(self, lesson_id: UUID) -> list[UUID]:
        """Return the head students of the lesson's groups."""
        lesson = self.store.lessons.get(lesson_id)
        if lesson is None:
            return []
        heads = [
            self.store.groups[g].head_student_id
            for g in audience_keys.group_ids(lesson.audience)
            if g in self.store.groups
        ]
        return [h for h in heads if h is not None]

    async def room_day(
        self, room_id: UUID, day: dt.date, locale: str
    ) -> list[LessonView]:
        """Return the room's lessons on a day ordered by period."""
        lessons = [
            lesson
            for lesson in self.store.lessons.values()
            if lesson.room_id == room_id
            and lesson.date == day
            and not on_a_saturday(lesson.date)
        ]
        lessons.sort(key=lambda x: (x.period, x.starts_at, str(x.id)))
        return [self._view(lesson, locale) for lesson in lessons]

    async def search_lessons(
        self, user_id: UUID, query: str, limit: int, locale: str
    ) -> list[LessonView]:
        """Search the user's lessons by subject or topic."""
        keys = self._keys(user_id)
        needle = query.strip().casefold()
        found = []
        for lesson in self.store.lessons.values():
            if on_a_saturday(lesson.date):
                continue
            mine = lesson.teacher_id == user_id or (
                keys is not None and set(lesson.audience) & set(keys)
            )
            subject = self.store.subjects[lesson.subject_id]
            texts = [lesson.topic or "", subject.short_name or ""]
            texts += [subject.name.get(lang, "") for lang in LANGUAGES]
            if mine and any(needle in text.casefold() for text in texts):
                found.append(lesson)
        found.sort(key=lambda x: (x.date, -x.period), reverse=True)
        return [self._view(lesson, locale) for lesson in found[:limit]]

    async def list_lessons(
        self,
        filters: LessonFilters,
        *,
        cursor: dict[str, Any] | None,
        limit: int,
        locale: str,
    ) -> LessonPage:
        """Return a page of lessons ordered by date, period and id."""
        lessons = [x for x in self.store.lessons.values() if _matches(x, filters)]
        lessons.sort(key=lambda x: (x.date, x.period, str(x.id)))
        if cursor is not None:
            after = (dt.date.fromisoformat(cursor["d"]), int(cursor["p"]), cursor["i"])
            lessons = [x for x in lessons if (x.date, x.period, str(x.id)) > after]
        page = lessons[:limit]
        next_cursor = None
        if len(lessons) > limit:
            last = page[-1]
            next_cursor = {
                "d": last.date.isoformat(),
                "p": last.period,
                "i": str(last.id),
            }
        return LessonPage([self._view(x, locale) for x in page], next_cursor)


def _matches(lesson: Lesson, filters: LessonFilters) -> bool:
    checks = [
        not on_a_saturday(lesson.date),
        filters.start is None or lesson.date >= filters.start,
        filters.end is None or lesson.date <= filters.end,
        filters.group_id is None
        or filters.group_id in audience_keys.group_ids(lesson.audience),
        filters.teacher_id is None or lesson.teacher_id == filters.teacher_id,
        filters.room_id is None or lesson.room_id == filters.room_id,
        filters.status is None or lesson.status == filters.status,
        filters.teacher_needed is None
        or (lesson.teacher_id is None) == filters.teacher_needed,
    ]
    return all(checks)
