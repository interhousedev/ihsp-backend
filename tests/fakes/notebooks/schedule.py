"""ScheduleQueries: audience, get_lesson and get_student for the notebooks tests."""

import dataclasses
import datetime as dt
from uuid import UUID

from app.shared.contracts.academic import LessonRef, StudentRef
from app.shared.ids import new_id
from tests.fakes.ai.contracts import FakeSchedule


class FakeLessonSchedule(FakeSchedule):
    """Lessons with an audience of students."""

    def __init__(self) -> None:
        """Start with no students; every student gets one group on demand."""
        super().__init__()
        self.group_id = new_id()
        self.emis_ids: dict[UUID, int] = {}  # subject id -> EMIS subject id
        self.taught: list[tuple[UUID, LessonRef]] = []  # (teacher id, lesson)
        self.placed: dict[UUID, tuple[UUID, int | None]] = {}  # student -> group, sub

    def place(self, user_id: UUID, group_id: UUID, subgroup: int | None = None) -> None:
        """Put the student in this group (and subgroup) instead of the default one."""
        self.placed[user_id] = (group_id, subgroup)

    def set_emis_id(self, subject_id: UUID, edu_subject_id: int) -> None:
        """The subject has this EMIS id (default materials are kept under it)."""
        self.emis_ids[subject_id] = edu_subject_id

    async def subject_emis_id(self, subject_id: UUID) -> int | None:
        """The EMIS id of the subject, None when it has none."""
        return self.emis_ids.get(subject_id)

    def attend(self, user_id: UUID, lesson: LessonRef) -> LessonRef:
        """Register the lesson and put the student in its audience."""
        if lesson not in self.lessons:
            self.lessons.append(lesson)
        self.audience.add((user_id, lesson.id))
        return lesson

    def teach(
        self, teacher_id: UUID, lesson: LessonRef, *groups: tuple[UUID, str]
    ) -> LessonRef:
        """The teacher gives the lesson to the groups (id, name)."""
        taught = dataclasses.replace(
            lesson,
            teacher_id=teacher_id,
            audience=tuple(str(group_id) for group_id, _ in groups),
            group_names=tuple(name for _, name in groups),
        )
        self.lessons.append(taught)
        self.taught.append((teacher_id, taught))
        return taught

    async def lessons_for_teacher(
        self, teacher_id: UUID, start: dt.date, end: dt.date
    ) -> list[LessonRef]:
        """The lessons the teacher gives between two dates."""
        return [
            lesson
            for who, lesson in self.taught
            if who == teacher_id and start <= lesson.date <= end
        ]

    async def lessons_for_student(
        self, user_id: UUID, start: dt.date, end: dt.date
    ) -> list[LessonRef]:
        """The lessons the student attends between two dates."""
        return [
            lesson
            for lesson in self.lessons
            if (user_id, lesson.id) in self.audience and start <= lesson.date <= end
        ]

    async def get_lesson(self, lesson_id: UUID) -> LessonRef | None:
        """Return the lesson."""
        return next((x for x in self.lessons if x.id == lesson_id), None)

    async def get_student(self, user_id: UUID) -> StudentRef | None:
        """Every student is in the same group without a subgroup, unless placed."""
        group_id, subgroup = self.placed.get(user_id, (self.group_id, None))
        return StudentRef(
            user_id=user_id,
            group_id=group_id,
            group_name="2TN2",
            subgroup=subgroup,
            status="active",
            synced_at=None,
        )
