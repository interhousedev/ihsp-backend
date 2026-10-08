"""Public APIs of the schedule: ScheduleQueries and AcademicEnrollment."""

import datetime as dt
from collections.abc import Sequence
from uuid import UUID

from app.modules.academic.application.schedule.common import (
    DEFAULT_LOCALE,
    UowFactory,
    today,
)
from app.modules.academic.application.schedule.ports.reader import ScheduleReader
from app.modules.academic.application.schedule.ports.unit_of_work import (
    ScheduleUnitOfWork,
)
from app.modules.academic.domain.schedule.errors import (
    GroupNameTakenError,
    GroupNotFoundError,
)
from app.modules.academic.domain.schedule.group import Group, clean_group_name
from app.modules.academic.domain.schedule.student import (
    CLOSING_GRACE_DAYS,
    Student,
)
from app.modules.academic.domain.schedule.subject import LANGUAGES, Subject
from app.modules.academic.domain.schedule.term import pick_current_term
from app.shared.clock import Clock
from app.shared.contracts.academic import LessonRef, RoomRef, StudentRef
from app.shared.contracts.emis import EmisSubject
from app.shared.contracts.identity import IdentityDirectory, UserStatus
from app.shared.ids import new_id
from app.shared.notifications import NotificationDraft, NotificationType

# - - - ScheduleQueries - - -


class ScheduleQueriesImpl:
    """Implements the ScheduleQueries contract over the schedule reader."""

    def __init__(self, reader: ScheduleReader, locale: str = DEFAULT_LOCALE) -> None:
        """Store the reader; subject names use the default locale."""
        self.reader = reader
        self.locale = locale

    async def get_student(self, user_id: UUID) -> StudentRef | None:
        """Return the student record or None."""
        return await self.reader.student_ref(user_id)

    async def get_lesson(self, lesson_id: UUID) -> LessonRef | None:
        """Return the lesson or None."""
        view = await self.reader.lesson_view(lesson_id, self.locale)
        return view.ref if view else None

    async def lessons_for_student(
        self, user_id: UUID, start: dt.date, end: dt.date
    ) -> list[LessonRef]:
        """Return the student's lessons of any status between two dates."""
        views = await self.reader.lessons_for_student(user_id, start, end, self.locale)
        return [view.ref for view in views]

    async def lessons_for_teacher(
        self, teacher_id: UUID, start: dt.date, end: dt.date
    ) -> list[LessonRef]:
        """Return the teacher's lessons of any status between two dates."""
        views = await self.reader.lessons_for_teacher(
            teacher_id, start, end, self.locale
        )
        return [view.ref for view in views]

    async def is_in_audience(self, user_id: UUID, lesson_id: UUID) -> bool:
        """Return True if the active student attends the lesson."""
        return await self.reader.is_in_audience(user_id, lesson_id)

    async def is_lesson_teacher(self, user_id: UUID, lesson_id: UUID) -> bool:
        """Return True if the user teaches the lesson."""
        return await self.reader.is_lesson_teacher(user_id, lesson_id)

    async def head_student_ids(self, lesson_id: UUID) -> list[UUID]:
        """Return head students of the groups in the lesson's audience."""
        return await self.reader.head_student_ids(lesson_id)

    async def room_by_slug(self, slug: str) -> RoomRef | None:
        """Return the room with this slug."""
        return await self.reader.room_by_slug(slug)

    async def room_day(self, room_id: UUID, day: dt.date) -> list[LessonRef]:
        """Return the room's lessons on a day ordered by period."""
        views = await self.reader.room_day(room_id, day, self.locale)
        return [view.ref for view in views]

    async def group_user_ids(
        self, group_ids: Sequence[UUID], semesters: Sequence[int] = ()
    ) -> list[UUID]:
        """Return user ids of active students of the groups and semesters.

        Empty group_ids with semesters means every group in those semesters.
        """
        return await self.reader.group_user_ids(group_ids, semesters)

    async def search_lessons(
        self, user_id: UUID, query: str, limit: int
    ) -> list[LessonRef]:
        """Search the user's lessons by subject, topic or homework."""
        views = await self.reader.search_lessons(user_id, query, limit, self.locale)
        return [view.ref for view in views]

    async def curated_group_ids(self, teacher_id: UUID) -> list[UUID]:
        """Return the groups the teacher curates."""
        return await self.reader.curated_group_ids(teacher_id)

    async def projected_lessons_for_student(
        self, user_id: UUID, start: dt.date, end: dt.date
    ) -> list[LessonRef]:
        """Return generated lessons plus lessons projected from the timetable."""
        views = await self.reader.projected_for_student(
            user_id, start, end, self.locale
        )
        return [view.ref for view in views]


# - - - AcademicEnrollment - - -


class AcademicEnrollmentImpl:
    """Implements AcademicEnrollment: registration, EMIS refresh and leaving."""

    def __init__(
        self, uow_factory: UowFactory, identity: IdentityDirectory, clock: Clock
    ) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory
        self.identity = identity
        self.clock = clock

    async def ensure_student(
        self,
        *,
        user_id: UUID,
        group_emis_id: int,
        group_name: str,
        current_semester: int | None,
        curriculum_id: int | None,
    ) -> StudentRef:
        """Create or update the student's group and row; a new group clears subgroup."""
        async with self.uow_factory() as uow:
            group = await self._upsert_group(
                uow, group_emis_id, group_name, current_semester, curriculum_id
            )
            student = await uow.students.get(user_id)
            if student is None:
                student = Student(user_id=user_id, group_id=group.id)
                await uow.students.add(student)
            else:
                student.move_to(group.id)
                await uow.students.save(student)
            needs_timetable = await self._lacks_timetable(uow, group.id)
            await uow.commit()
        return StudentRef(
            user_id=student.user_id,
            group_id=group.id,
            group_name=group.name,
            subgroup=student.subgroup,
            status=student.status,
            synced_at=student.synced_at,
            needs_timetable=needs_timetable,
        )

    async def _lacks_timetable(self, uow: ScheduleUnitOfWork, group_id: UUID) -> bool:
        """True when a current term exists and the group has no entries in it."""
        term = pick_current_term(await uow.terms.list_all(), today(self.clock))
        if term is None:
            return False
        return not await uow.entries.search(term.id, group_id=group_id)

    async def _upsert_group(
        self,
        uow: ScheduleUnitOfWork,
        emis_id: int,
        group_name: str,
        semester: int | None,
        curriculum_id: int | None,
    ) -> Group:
        name, slug = clean_group_name(group_name)
        group = await uow.groups.get_by_emis_id(emis_id)
        if group is None:
            group = await self._adopt_or_create(uow, emis_id, name, slug)
        elif group.slug != slug or group.status != "active":
            await self._free_slug(uow, slug, keep=group.id)
            group.name, group.slug, group.status = name, slug, "active"
        group.current_semester = semester
        group.emis_curriculum_id = curriculum_id
        await uow.groups.save(group)
        return group

    async def _adopt_or_create(
        self, uow: ScheduleUnitOfWork, emis_id: int, name: str, slug: str
    ) -> Group:
        """Link a group made in advance (same name) or create a new one."""
        waiting = await uow.groups.find_active_by_slug(slug)
        if waiting is not None and waiting.emis_group_id is None:
            waiting.emis_group_id = emis_id
            return waiting
        await self._free_slug(uow, slug, keep=None)
        group = Group(id=new_id(), name=name, slug=slug, emis_group_id=emis_id)
        await uow.groups.add(group)
        return group

    @staticmethod
    async def _free_slug(
        uow: ScheduleUnitOfWork, slug: str, *, keep: UUID | None
    ) -> None:
        """Archive an empty group that holds the slug; refuse if it has students."""
        clash = await uow.groups.find_active_by_slug(slug)
        if clash is None or clash.id == keep:
            return
        members = await uow.students.list_filtered(group_id=clash.id, status="active")
        if members:
            raise GroupNameTakenError(params={"name": clash.name})
        clash.status = "archived"
        await uow.groups.save(clash)

    async def find_imported_student(
        self,
        *,
        emis_student_id: int | None,
        first_name: str,
        last_name: str,
        group_name: str,
    ) -> UUID | None:
        """Return the one unregistered imported student with this name in the group.

        Matching by EMIS id is done by the identity module before this call.
        """
        _, slug = clean_group_name(group_name)
        async with self.uow_factory() as uow:
            group = await uow.groups.find_active_by_slug(slug)
            if group is None:
                return None
            students = await uow.students.list_filtered(
                group_id=group.id, status="active"
            )
        users = await self.identity.get_users([s.user_id for s in students])
        wanted = (first_name.strip().casefold(), last_name.strip().casefold())
        matches = [
            user.id
            for user in users.values()
            if user.status == UserStatus.UNREGISTERED
            and (user.first_name.casefold(), user.last_name.casefold()) == wanted
        ]
        return matches[0] if len(matches) == 1 else None

    async def sync_subjects(
        self, *, group_id: UUID, subjects: Sequence[EmisSubject]
    ) -> None:
        """Upsert subjects by EMIS id and set the group's curriculum list."""
        async with self.uow_factory() as uow:
            group = await uow.groups.get(group_id)
            if group is None:
                raise GroupNotFoundError()
            ids: list[UUID] = []
            for item in subjects:
                subject = await self._upsert_subject(uow, item)
                if subject.id not in ids:
                    ids.append(subject.id)
            group.subject_ids = ids
            await uow.groups.save(group)
            await uow.commit()

    @staticmethod
    async def _upsert_subject(uow: ScheduleUnitOfWork, item: EmisSubject) -> Subject:
        names = {"uz": item.name_uz, "ru": item.name_ru, "en": item.name_en}
        subject = await uow.subjects.get_by_emis_id(item.emis_subject_id)
        if subject is None:
            subject = Subject(
                id=new_id(),
                name={lang: names[lang].strip() for lang in LANGUAGES},
                emis_subject_id=item.emis_subject_id,
            )
            await uow.subjects.add(subject)
            return subject
        for lang in LANGUAGES:
            fresh = names[lang].strip()
            if fresh:
                subject.name[lang] = fresh
        await uow.subjects.save(subject)
        return subject

    async def mark_left(self, user_id: UUID, *, reason: str) -> None:
        """Mark the student as left and announce that the account closes in 30 days."""
        async with self.uow_factory() as uow:
            student = await uow.students.get(user_id)
            if student is None or student.status == "left":
                return
            day = today(self.clock)
            student.leave(today=day, reason=reason)
            await uow.students.save(student)
            uow.notify(
                NotificationDraft(
                    user_id=user_id,
                    type=NotificationType.ACCOUNT_CLOSING,
                    payload={
                        "closes_on": (
                            day + dt.timedelta(days=CLOSING_GRACE_DAYS)
                        ).isoformat()
                    },
                    dedupe_key=f"account-closing:{user_id}",
                )
            )
            await uow.commit()
