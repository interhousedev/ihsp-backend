"""In-memory repositories that behave like the SQL ones (constraints included)."""

import copy
import datetime as dt
from collections.abc import Collection, Sequence
from uuid import UUID

from app.modules.academic.domain import audience as audience_keys
from app.modules.academic.domain.schedule.conflicts import LessonSlot, lesson_conflicts
from app.modules.academic.domain.schedule.errors import RoomSlugTakenError
from app.modules.academic.domain.schedule.group import Group
from app.modules.academic.domain.schedule.lesson import Lesson
from app.modules.academic.domain.schedule.room import Room
from app.modules.academic.domain.schedule.student import Student
from app.modules.academic.domain.schedule.subject import LANGUAGES, Subject
from app.modules.academic.domain.schedule.term import Term
from app.modules.academic.domain.schedule.timetable_entry import TimetableEntry
from app.shared.base_error import ConflictError
from tests.fakes.academic.schedule.store import ScheduleStore


def _copy[T](value: T) -> T:
    return copy.deepcopy(value)


class FakeTermRepository:
    """Terms."""

    def __init__(self, store: ScheduleStore) -> None:
        """Bind to the store."""
        self.store = store

    async def get(self, term_id: UUID) -> Term | None:
        """Return a copy of the term."""
        term = self.store.terms.get(term_id)
        return _copy(term) if term else None

    async def list_all(self) -> list[Term]:
        """Return terms by start date."""
        return [_copy(t) for t in sorted(self.store.terms.values(), key=_start)]

    async def add(self, term: Term) -> None:
        """Insert a term."""
        self.store.terms[term.id] = _copy(term)

    async def save(self, term: Term) -> None:
        """Replace a term."""
        self.store.terms[term.id] = _copy(term)

    async def overlapping(
        self, starts_on: dt.date, ends_on: dt.date, *, exclude_id: UUID | None
    ) -> list[Term]:
        """Return terms intersecting the range."""
        return [
            _copy(t)
            for t in sorted(self.store.terms.values(), key=_start)
            if t.starts_on <= ends_on and t.ends_on >= starts_on and t.id != exclude_id
        ]

    async def year_half_taken(
        self, academic_year: str, half: int, *, exclude_id: UUID | None
    ) -> bool:
        """Return True if another term has this year and half."""
        return any(
            t.academic_year == academic_year and t.half == half and t.id != exclude_id
            for t in self.store.terms.values()
        )

    async def containing(self, day: dt.date) -> Term | None:
        """Return the term containing the day."""
        for term in self.store.terms.values():
            if term.contains(day):
                return _copy(term)
        return None


def _start(term: Term) -> dt.date:
    return term.starts_on


class FakeGroupRepository:
    """Groups."""

    def __init__(self, store: ScheduleStore) -> None:
        """Bind to the store."""
        self.store = store

    async def get(self, group_id: UUID) -> Group | None:
        """Return a copy of the group."""
        group = self.store.groups.get(group_id)
        return _copy(group) if group else None

    async def get_many(self, group_ids: Collection[UUID]) -> dict[UUID, Group]:
        """Return the groups that exist."""
        return {
            g: _copy(self.store.groups[g]) for g in group_ids if g in self.store.groups
        }

    async def get_by_emis_id(self, emis_group_id: int) -> Group | None:
        """Return the group linked to an EMIS id."""
        for group in self.store.groups.values():
            if group.emis_group_id == emis_group_id:
                return _copy(group)
        return None

    async def find_active_by_slug(self, slug: str) -> Group | None:
        """Return the active group with the slug."""
        for group in self.store.groups.values():
            if group.slug == slug and group.status == "active":
                return _copy(group)
        return None

    async def add(self, group: Group) -> None:
        """Insert a group; slugs are unique among active groups."""
        self._check_slug(group)
        self.store.groups[group.id] = _copy(group)

    async def save(self, group: Group) -> None:
        """Replace a group."""
        self._check_slug(group)
        self.store.groups[group.id] = _copy(group)

    def _check_slug(self, group: Group) -> None:
        if group.status != "active":
            return
        for other in self.store.groups.values():
            if (
                other.id != group.id
                and other.status == "active"
                and other.slug == group.slug
            ):
                raise ConflictError(support_details="ix_groups_slug_active")

    async def list_all(self, status: str | None = None) -> list[Group]:
        """Return groups by name."""
        groups = sorted(self.store.groups.values(), key=lambda g: g.name)
        return [_copy(g) for g in groups if status is None or g.status == status]

    async def curated_by(self, teacher_id: UUID) -> list[Group]:
        """Return the active groups the teacher curates."""
        groups = sorted(self.store.groups.values(), key=lambda g: g.name)
        return [
            _copy(g)
            for g in groups
            if g.curator_id == teacher_id and g.status == "active"
        ]


class FakeStudentRepository:
    """Students."""

    def __init__(self, store: ScheduleStore) -> None:
        """Bind to the store."""
        self.store = store

    async def get(self, user_id: UUID) -> Student | None:
        """Return a copy of the student."""
        student = self.store.students.get(user_id)
        return _copy(student) if student else None

    async def get_many(self, user_ids: Collection[UUID]) -> dict[UUID, Student]:
        """Return the students that exist."""
        return {
            u: _copy(self.store.students[u])
            for u in user_ids
            if u in self.store.students
        }

    async def add(self, student: Student) -> None:
        """Insert a student."""
        self.store.students[student.user_id] = _copy(student)

    async def save(self, student: Student) -> None:
        """Replace a student."""
        self.store.students[student.user_id] = _copy(student)

    async def list_filtered(
        self,
        *,
        group_id: UUID | None = None,
        subgroup: int | None = None,
        status: str | None = None,
    ) -> list[Student]:
        """Return students matching the filters."""
        return [
            _copy(s)
            for s in self.store.students.values()
            if (group_id is None or s.group_id == group_id)
            and (subgroup is None or s.subgroup == subgroup)
            and (status is None or s.status == status)
        ]

    async def user_ids_for_audience(self, keys: Sequence[str]) -> list[UUID]:
        """Return active students who attend a lesson with these audience keys."""
        parsed = [audience_keys.parse(key) for key in keys]
        return [
            s.user_id
            for s in self.store.students.values()
            if s.status == "active" and _attends(s, parsed)
        ]

    async def set_calendar_token_hash(self, user_id: UUID, token_hash: str) -> bool:
        """Store the token hash of an existing student."""
        if user_id not in self.store.students:
            return False
        self.store.calendar_tokens[user_id] = token_hash
        return True

    async def user_id_for_calendar_token(self, token_hash: str) -> UUID | None:
        """Return the active student who owns the token hash."""
        return next(
            (
                user_id
                for user_id, stored in self.store.calendar_tokens.items()
                if stored == token_hash
                and self.store.students[user_id].status == "active"
            ),
            None,
        )


def _attends(student: Student, parsed: list[tuple[UUID, int | None]]) -> bool:
    for group_id, subgroup in parsed:
        if student.group_id != group_id:
            continue
        if subgroup is None or student.subgroup is None or student.subgroup == subgroup:
            return True
    return False


class FakeSubjectRepository:
    """Subjects."""

    def __init__(self, store: ScheduleStore) -> None:
        """Bind to the store."""
        self.store = store

    async def get(self, subject_id: UUID) -> Subject | None:
        """Return a copy of the subject."""
        subject = self.store.subjects.get(subject_id)
        return _copy(subject) if subject else None

    async def get_many(self, subject_ids: Collection[UUID]) -> dict[UUID, Subject]:
        """Return the subjects that exist."""
        return {
            s: _copy(self.store.subjects[s])
            for s in subject_ids
            if s in self.store.subjects
        }

    async def get_by_emis_id(self, emis_subject_id: int) -> Subject | None:
        """Return the subject linked to an EMIS id."""
        for subject in self.store.subjects.values():
            if subject.emis_subject_id == emis_subject_id:
                return _copy(subject)
        return None

    async def add(self, subject: Subject) -> None:
        """Insert a subject."""
        self.store.subjects[subject.id] = _copy(subject)

    async def save(self, subject: Subject) -> None:
        """Replace a subject."""
        self.store.subjects[subject.id] = _copy(subject)

    async def search(self, query: str | None) -> list[Subject]:
        """Return subjects whose names contain the query."""
        needle = (query or "").casefold()

        def matches(subject: Subject) -> bool:
            texts = [subject.name.get(lang, "") for lang in LANGUAGES]
            texts.append(subject.short_name or "")
            return not needle or any(needle in text.casefold() for text in texts)

        found = [s for s in self.store.subjects.values() if matches(s)]
        found.sort(
            key=lambda s: (
                s.name.get("ru") or s.name.get("uz") or s.name.get("en") or ""
            )
        )
        return [_copy(s) for s in found]


class FakeRoomRepository:
    """Rooms."""

    def __init__(self, store: ScheduleStore) -> None:
        """Bind to the store."""
        self.store = store

    async def get(self, room_id: UUID) -> Room | None:
        """Return a copy of the room."""
        room = self.store.rooms.get(room_id)
        return _copy(room) if room else None

    async def get_many(self, room_ids: Collection[UUID]) -> dict[UUID, Room]:
        """Return the rooms that exist."""
        return {
            r: _copy(self.store.rooms[r]) for r in room_ids if r in self.store.rooms
        }

    async def get_by_slug(self, slug: str) -> Room | None:
        """Return the room with the slug."""
        for room in self.store.rooms.values():
            if room.slug == slug:
                return _copy(room)
        return None

    async def add(self, room: Room) -> None:
        """Insert a room; slugs are unique."""
        self._check(room)
        self.store.rooms[room.id] = _copy(room)

    async def save(self, room: Room) -> None:
        """Replace a room."""
        self._check(room)
        self.store.rooms[room.id] = _copy(room)

    def _check(self, room: Room) -> None:
        for other in self.store.rooms.values():
            if other.id != room.id and other.slug == room.slug:
                raise RoomSlugTakenError(params={"slug": room.slug})

    async def list_all(self, status: str | None = None) -> list[Room]:
        """Return rooms by name."""
        rooms = sorted(self.store.rooms.values(), key=lambda r: r.name)
        return [_copy(r) for r in rooms if status is None or r.status == status]


class FakeTimetableEntryRepository:
    """Timetable entries."""

    def __init__(self, store: ScheduleStore) -> None:
        """Bind to the store."""
        self.store = store

    async def get(self, entry_id: UUID) -> TimetableEntry | None:
        """Return a copy of the entry."""
        entry = self.store.entries.get(entry_id)
        return _copy(entry) if entry else None

    async def add(self, entry: TimetableEntry) -> None:
        """Insert an entry."""
        self.store.entries[entry.id] = _copy(entry)

    async def save(self, entry: TimetableEntry) -> None:
        """Replace an entry."""
        self.store.entries[entry.id] = _copy(entry)

    async def delete(self, entry_id: UUID) -> None:
        """Delete an entry; lessons keep no reference to it (ON DELETE SET NULL)."""
        self.store.entries.pop(entry_id, None)
        for lesson in self.store.lessons.values():
            if lesson.timetable_entry_id == entry_id:
                lesson.timetable_entry_id = None

    async def list_for_term(self, term_id: UUID) -> list[TimetableEntry]:
        """Return the term's entries."""
        return [_copy(e) for e in self.store.entries.values() if e.term_id == term_id]

    async def search(
        self,
        term_id: UUID,
        *,
        group_id: UUID | None = None,
        teacher_id: UUID | None = None,
        room_id: UUID | None = None,
    ) -> list[TimetableEntry]:
        """Return entries of a group, teacher or room."""
        found = []
        for entry in self.store.entries.values():
            if entry.term_id != term_id:
                continue
            groups = audience_keys.group_ids(entry.audience)
            if group_id is not None and group_id not in groups:
                continue
            if teacher_id is not None and entry.teacher_id != teacher_id:
                continue
            if room_id is not None and entry.room_id != room_id:
                continue
            found.append(_copy(entry))
        return found

    async def same_slot(
        self, term_id: UUID, weekday: int, period: int
    ) -> list[TimetableEntry]:
        """Return entries at one weekday and period."""
        return [
            _copy(e)
            for e in self.store.entries.values()
            if e.term_id == term_id and e.weekday == weekday and e.period == period
        ]

    async def clear_teacher(self, teacher_id: UUID) -> int:
        """Clear the teacher on their entries."""
        count = 0
        for entry in self.store.entries.values():
            if entry.teacher_id == teacher_id:
                entry.teacher_id = None
                count += 1
        return count

    async def reassign_room(self, source_id: UUID, target_id: UUID) -> int:
        """Move entries to another room."""
        count = 0
        for entry in self.store.entries.values():
            if entry.room_id == source_id:
                entry.room_id = target_id
                count += 1
        return count


class FakeLessonRepository:
    """Lessons, with the same teacher/room overlap rule as the exclusion constraints."""

    def __init__(self, store: ScheduleStore) -> None:
        """Bind to the store."""
        self.store = store

    async def get(self, lesson_id: UUID) -> Lesson | None:
        """Return a copy of the lesson."""
        lesson = self.store.lessons.get(lesson_id)
        return _copy(lesson) if lesson else None

    def _clash(self, lesson: Lesson) -> bool:
        if lesson.status != "scheduled":
            return False
        slot = LessonSlot(
            lesson.id,
            lesson.starts_at,
            lesson.ends_at,
            lesson.teacher_id,
            lesson.room_id,
            [],
        )
        others = [o for o in self.store.lessons.values() if o.id != lesson.id]
        return bool(lesson_conflicts(slot, others))

    def _check(self, lesson: Lesson) -> None:
        if self._clash(lesson):
            raise ConflictError(params={"conflicts": [{"kind": "teacher"}]})

    async def add(self, lesson: Lesson) -> None:
        """Insert a lesson; a teacher or room overlap raises ConflictError."""
        self._check(lesson)
        self.store.lessons[lesson.id] = _copy(lesson)

    async def try_add(self, lesson: Lesson) -> bool:
        """Insert unless the exclusion rule blocks it."""
        if self._clash(lesson):
            return False
        self.store.lessons[lesson.id] = _copy(lesson)
        return True

    async def save(self, lesson: Lesson) -> None:
        """Replace a lesson; a teacher or room overlap raises ConflictError."""
        self._check(lesson)
        self.store.lessons[lesson.id] = _copy(lesson)

    async def try_save(self, lesson: Lesson) -> bool:
        """Replace unless the exclusion rule blocks it."""
        if self._clash(lesson):
            return False
        self.store.lessons[lesson.id] = _copy(lesson)
        return True

    async def delete_many(self, lesson_ids: Collection[UUID]) -> None:
        """Delete lessons."""
        for lesson_id in lesson_ids:
            self.store.lessons.pop(lesson_id, None)

    async def generated_in_range(
        self, term_id: UUID, start: dt.date, end: dt.date
    ) -> list[Lesson]:
        """Return generated lessons whose origin date is in the range."""
        return [
            _copy(lesson)
            for lesson in self.store.lessons.values()
            if lesson.term_id == term_id
            and lesson.timetable_entry_id is not None
            and lesson.origin_date is not None
            and start <= lesson.origin_date <= end
        ]

    async def in_audience(
        self, term_id: UUID, start: dt.date, end: dt.date, keys: Collection[str]
    ) -> list[Lesson]:
        """Return the term's lessons dated start..end whose audience holds a key."""
        wanted = set(keys)
        found = [
            _copy(lesson)
            for lesson in self.store.lessons.values()
            if lesson.term_id == term_id
            and start <= lesson.date <= end
            and wanted & set(lesson.audience)
        ]
        return sorted(found, key=lambda x: (x.date, x.period, str(x.id)))

    async def with_emis_class_ids(self, class_ids: Collection[int]) -> list[Lesson]:
        """Return the lessons that mirror one of the EMIS classes."""
        return [
            _copy(lesson)
            for lesson in self.store.lessons.values()
            if lesson.emis_class_id in class_ids
        ]

    async def find_overlapping(
        self, starts_at: dt.datetime, ends_at: dt.datetime
    ) -> list[Lesson]:
        """Return scheduled lessons overlapping the interval."""
        return [
            _copy(lesson)
            for lesson in self.store.lessons.values()
            if lesson.status == "scheduled"
            and lesson.starts_at < ends_at
            and lesson.ends_at > starts_at
        ]

    async def reassign_room(self, source_id: UUID, target_id: UUID) -> int:
        """Move lessons to another room."""
        moved = [
            lesson
            for lesson in self.store.lessons.values()
            if lesson.room_id == source_id
        ]
        for lesson in moved:
            lesson.room_id = target_id
        for lesson in moved:
            self._check(lesson)
        return len(moved)

    async def clear_teacher_future(
        self, teacher_id: UUID, now: dt.datetime
    ) -> list[UUID]:
        """Clear the teacher on lessons that have not started."""
        cleared = []
        for lesson in self.store.lessons.values():
            if lesson.teacher_id == teacher_id and lesson.starts_at > now:
                lesson.teacher_id = None
                cleared.append(lesson.id)
        return cleared

    async def count_future_in_room(self, room_id: UUID, now: dt.datetime) -> int:
        """Count scheduled future lessons in the room."""
        return sum(
            1
            for lesson in self.store.lessons.values()
            if lesson.room_id == room_id
            and lesson.status == "scheduled"
            and lesson.starts_at > now
        )

    async def count_by_room(self, start: dt.date, end: dt.date) -> dict[UUID, int]:
        """Count scheduled lessons per room."""
        counts: dict[UUID, int] = {}
        for lesson in self.store.lessons.values():
            if (
                lesson.room_id is not None
                and lesson.status == "scheduled"
                and start <= lesson.date <= end
            ):
                counts[lesson.room_id] = counts.get(lesson.room_id, 0) + 1
        return counts

    async def detach_entry(self, entry_id: UUID, now: dt.datetime) -> list[UUID]:
        """Delete or cancel the entry's future lessons and unlink all of them."""
        affected: list[UUID] = []
        for lesson in list(self.store.lessons.values()):
            if lesson.timetable_entry_id != entry_id:
                continue
            lesson.timetable_entry_id = None
            if lesson.is_overridden or lesson.starts_at <= now:
                continue
            affected.append(lesson.id)
            if lesson.has_content:
                lesson.status = "cancelled"
            else:
                del self.store.lessons[lesson.id]
        return affected
