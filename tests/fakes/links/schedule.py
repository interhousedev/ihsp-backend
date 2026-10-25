"""In-memory ScheduleQueries with lessons, rooms, teachers and audiences."""

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from uuid import UUID

from app.shared.contracts.academic import (
    LessonGroupRef,
    LessonRef,
    RoomRef,
    StudentRef,
)
from app.shared.ids import new_id

DAY_START = datetime(2026, 10, 6, 4, 55, tzinfo=UTC)  # 09:55 in Tashkent
DEFAULT_DAY = date(2026, 10, 6)


class FakeSchedule:
    """Lessons by id; membership sets decide teacher and audience checks."""

    def __init__(self) -> None:
        """Start empty."""
        self.lessons: dict[UUID, LessonRef] = {}
        self.rooms: dict[str, RoomRef] = {}
        self.teachers: dict[UUID, set[UUID]] = {}
        self.audience: dict[UUID, set[UUID]] = {}
        self.groups: dict[UUID, list[tuple[UUID, str]]] = {}

    def add_room(
        self,
        slug: str = "102",
        *,
        pin: str = "483920",
        status: Literal["active", "archived"] = "active",
    ) -> RoomRef:
        """Create a room."""
        room = RoomRef(id=new_id(), slug=slug, name=slug, pin=pin, status=status)
        self.rooms[slug] = room
        return room

    def add_lesson(
        self,
        *,
        day: date = DEFAULT_DAY,
        period: int = 3,
        subject_id: UUID | None = None,
        subject_name: str = "Physics",
        teacher_id: UUID | None = None,
        room: RoomRef | None = None,
        group_names: tuple[str, ...] = ("2TN2",),
        students: Sequence[UUID] = (),
        status: Literal["scheduled", "cancelled"] = "scheduled",
        groups: Sequence[tuple[UUID, str]] = (),
    ) -> LessonRef:
        """Create a lesson on `day`; it runs 45 minutes from 09:55 local time."""
        base = datetime.combine(day, DAY_START.timetz()) + timedelta(
            minutes=55 * (period - 3)
        )
        lesson = LessonRef(
            id=new_id(),
            date=day,
            period=period,
            starts_at=base,
            ends_at=base + timedelta(minutes=45),
            subject_id=subject_id or new_id(),
            subject_name=subject_name,
            teacher_id=teacher_id,
            room_id=room.id if room else None,
            room_slug=room.slug if room else None,
            room_name=room.name if room else None,
            audience=(),
            group_names=group_names,
            status=status,
            topic=None,
            homework_text=None,
            homework_due_date=None,
        )
        self.lessons[lesson.id] = lesson
        if teacher_id is not None:
            self.teachers.setdefault(lesson.id, set()).add(teacher_id)
        self.audience[lesson.id] = set(students)
        self.groups[lesson.id] = list(groups)
        return lesson

    async def lesson_groups(
        self,
        *,
        subject_id: UUID | None = None,
        lesson_ids: Sequence[UUID] | None = None,
        teacher_id: UUID | None = None,
        group_id: UUID | None = None,
    ) -> list[LessonGroupRef]:
        """Return (lesson, group) pairs of the lessons added with groups."""
        return [
            LessonGroupRef(
                lesson_id=x.id,
                date=x.date,
                subject_id=x.subject_id,
                teacher_id=x.teacher_id,
                group_id=gid,
                group_name=name,
            )
            for x in sorted(self.lessons.values(), key=lambda x: x.starts_at)
            if (subject_id is None or x.subject_id == subject_id)
            and (lesson_ids is None or x.id in lesson_ids)
            and (teacher_id is None or x.teacher_id == teacher_id)
            for gid, name in self.groups.get(x.id, [])
            if group_id is None or gid == group_id
        ]

    async def get_student(self, user_id: UUID) -> StudentRef | None:
        """Return nothing."""
        return None

    async def get_lesson(self, lesson_id: UUID) -> LessonRef | None:
        """Return the lesson or None."""
        return self.lessons.get(lesson_id)

    async def lessons_for_student(
        self, user_id: UUID, start: date, end: date
    ) -> list[LessonRef]:
        """Return no lessons."""
        return []

    async def lessons_for_teacher(
        self, teacher_id: UUID, start: date, end: date
    ) -> list[LessonRef]:
        """Return no lessons."""
        return []

    async def is_in_audience(self, user_id: UUID, lesson_id: UUID) -> bool:
        """True for students registered for the lesson."""
        return user_id in self.audience.get(lesson_id, set())

    async def is_lesson_teacher(self, user_id: UUID, lesson_id: UUID) -> bool:
        """True for the lesson's teachers."""
        return user_id in self.teachers.get(lesson_id, set())

    async def head_student_ids(self, lesson_id: UUID) -> list[UUID]:
        """Return no head students."""
        return []

    async def room_by_slug(self, slug: str) -> RoomRef | None:
        """Return the room or None."""
        return self.rooms.get(slug)

    async def room_day(self, room_id: UUID, day: date) -> list[LessonRef]:
        """Return the room's lessons of the day."""
        return [
            lesson
            for lesson in self.lessons.values()
            if lesson.room_id == room_id and lesson.date == day
        ]

    async def group_user_ids(
        self, group_ids: Sequence[UUID], semesters: Sequence[int] = ()
    ) -> list[UUID]:
        """Return no users."""
        return []

    async def search_lessons(
        self, user_id: UUID, query: str, limit: int
    ) -> list[LessonRef]:
        """Return no lessons."""
        return []

    async def curated_group_ids(self, teacher_id: UUID) -> list[UUID]:
        """Return no groups."""
        return []

    async def projected_lessons_for_student(
        self, user_id: UUID, start: date, end: date
    ) -> list[LessonRef]:
        """Return no lessons."""
        return []
