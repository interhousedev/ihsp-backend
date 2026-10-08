"""Repository ports of the academic schedule."""

import datetime as dt
from collections.abc import Collection, Sequence
from typing import Protocol
from uuid import UUID

from app.modules.academic.domain.schedule.group import Group
from app.modules.academic.domain.schedule.lesson import Lesson
from app.modules.academic.domain.schedule.room import Room
from app.modules.academic.domain.schedule.student import Student
from app.modules.academic.domain.schedule.subject import Subject
from app.modules.academic.domain.schedule.term import Term
from app.modules.academic.domain.schedule.timetable_entry import TimetableEntry


class TermRepository(Protocol):
    """Terms and their calendars."""

    async def get(self, term_id: UUID) -> Term | None:
        """Return the term or None."""
        ...

    async def list_all(self) -> list[Term]:
        """Return all terms ordered by start date."""
        ...

    async def add(self, term: Term) -> None:
        """Insert a term."""
        ...

    async def save(self, term: Term) -> None:
        """Write the changes of a term."""
        ...

    async def overlapping(
        self, starts_on: dt.date, ends_on: dt.date, *, exclude_id: UUID | None
    ) -> list[Term]:
        """Return terms whose dates intersect the range."""
        ...

    async def year_half_taken(
        self, academic_year: str, half: int, *, exclude_id: UUID | None
    ) -> bool:
        """Return True if another term has this academic year and half."""
        ...

    async def containing(self, day: dt.date) -> Term | None:
        """Return the term whose dates contain the day."""
        ...


class GroupRepository(Protocol):
    """Groups."""

    async def get(self, group_id: UUID) -> Group | None:
        """Return the group or None."""
        ...

    async def get_many(self, group_ids: Collection[UUID]) -> dict[UUID, Group]:
        """Return the groups that exist, by id."""
        ...

    async def get_by_emis_id(self, emis_group_id: int) -> Group | None:
        """Return the group linked to an EMIS group."""
        ...

    async def find_active_by_slug(self, slug: str) -> Group | None:
        """Return the active group with this slug."""
        ...

    async def add(self, group: Group) -> None:
        """Insert a group."""
        ...

    async def save(self, group: Group) -> None:
        """Write the changes of a group."""
        ...

    async def list_all(self, status: str | None = None) -> list[Group]:
        """Return groups ordered by name, optionally of one status."""
        ...

    async def curated_by(self, teacher_id: UUID) -> list[Group]:
        """Return the active groups a teacher curates."""
        ...


class StudentRepository(Protocol):
    """Academic student rows."""

    async def get(self, user_id: UUID) -> Student | None:
        """Return the student or None."""
        ...

    async def get_many(self, user_ids: Collection[UUID]) -> dict[UUID, Student]:
        """Return the students that exist, by user id."""
        ...

    async def add(self, student: Student) -> None:
        """Insert a student."""
        ...

    async def save(self, student: Student) -> None:
        """Write the changes of a student."""
        ...

    async def list_filtered(
        self,
        *,
        group_id: UUID | None = None,
        subgroup: int | None = None,
        status: str | None = None,
    ) -> list[Student]:
        """Return students matching the filters (all when none are given)."""
        ...

    async def user_ids_for_audience(self, keys: Sequence[str]) -> list[UUID]:
        """Return active students who attend a lesson with these audience keys."""
        ...

    async def set_calendar_token_hash(self, user_id: UUID, token_hash: str) -> bool:
        """Store the hash of the student's iCal feed token; False if no such student."""
        ...

    async def user_id_for_calendar_token(self, token_hash: str) -> UUID | None:
        """Return the active student whose iCal feed token has this hash."""
        ...


class SubjectRepository(Protocol):
    """Subjects."""

    async def get(self, subject_id: UUID) -> Subject | None:
        """Return the subject or None."""
        ...

    async def get_many(self, subject_ids: Collection[UUID]) -> dict[UUID, Subject]:
        """Return the subjects that exist, by id."""
        ...

    async def get_by_emis_id(self, emis_subject_id: int) -> Subject | None:
        """Return the subject linked to an EMIS subject."""
        ...

    async def add(self, subject: Subject) -> None:
        """Insert a subject."""
        ...

    async def save(self, subject: Subject) -> None:
        """Write the changes of a subject."""
        ...

    async def search(self, query: str | None) -> list[Subject]:
        """Return subjects whose names contain the query, ordered by name."""
        ...


class RoomRepository(Protocol):
    """Rooms."""

    async def get(self, room_id: UUID) -> Room | None:
        """Return the room or None."""
        ...

    async def get_many(self, room_ids: Collection[UUID]) -> dict[UUID, Room]:
        """Return the rooms that exist, by id."""
        ...

    async def get_by_slug(self, slug: str) -> Room | None:
        """Return the room with this slug (any status)."""
        ...

    async def add(self, room: Room) -> None:
        """Insert a room."""
        ...

    async def save(self, room: Room) -> None:
        """Write the changes of a room."""
        ...

    async def list_all(self, status: str | None = None) -> list[Room]:
        """Return rooms ordered by name, optionally of one status."""
        ...


class TimetableEntryRepository(Protocol):
    """Timetable entries."""

    async def get(self, entry_id: UUID) -> TimetableEntry | None:
        """Return the entry or None."""
        ...

    async def add(self, entry: TimetableEntry) -> None:
        """Insert an entry."""
        ...

    async def save(self, entry: TimetableEntry) -> None:
        """Write the changes of an entry."""
        ...

    async def delete(self, entry_id: UUID) -> None:
        """Delete an entry."""
        ...

    async def list_for_term(self, term_id: UUID) -> list[TimetableEntry]:
        """Return every entry of the term."""
        ...

    async def search(
        self,
        term_id: UUID,
        *,
        group_id: UUID | None = None,
        teacher_id: UUID | None = None,
        room_id: UUID | None = None,
    ) -> list[TimetableEntry]:
        """Return the term's entries of a group, a teacher or a room."""
        ...

    async def same_slot(
        self, term_id: UUID, weekday: int, period: int
    ) -> list[TimetableEntry]:
        """Return entries of the term at one weekday and period."""
        ...

    async def clear_teacher(self, teacher_id: UUID) -> int:
        """Set teacher_id to NULL on the teacher's entries; return how many."""
        ...

    async def reassign_room(self, source_id: UUID, target_id: UUID) -> int:
        """Move entries from one room to another; return how many."""
        ...


class LessonRepository(Protocol):
    """Lessons (schedule columns only)."""

    async def get(self, lesson_id: UUID) -> Lesson | None:
        """Return the lesson or None."""
        ...

    async def add(self, lesson: Lesson) -> None:
        """Insert a lesson."""
        ...

    async def try_add(self, lesson: Lesson) -> bool:
        """Insert unless a time conflict blocks it; return whether it was added."""
        ...

    async def save(self, lesson: Lesson) -> None:
        """Write the schedule columns of a lesson."""
        ...

    async def try_save(self, lesson: Lesson) -> bool:
        """Write unless a time conflict blocks it; return whether it was saved."""
        ...

    async def delete_many(self, lesson_ids: Collection[UUID]) -> None:
        """Delete lessons."""
        ...

    async def generated_in_range(
        self, term_id: UUID, start: dt.date, end: dt.date
    ) -> list[Lesson]:
        """Return lessons made from entries whose origin date is in the range."""
        ...

    async def find_overlapping(
        self, starts_at: dt.datetime, ends_at: dt.datetime
    ) -> list[Lesson]:
        """Return scheduled lessons whose time intersects the interval."""
        ...

    async def reassign_room(self, source_id: UUID, target_id: UUID) -> int:
        """Move lessons from one room to another; return how many."""
        ...

    async def clear_teacher_future(
        self, teacher_id: UUID, now: dt.datetime
    ) -> list[UUID]:
        """Set teacher_id to NULL on lessons not started yet; return their ids."""
        ...

    async def count_future_in_room(self, room_id: UUID, now: dt.datetime) -> int:
        """Count scheduled lessons in the room that have not started."""
        ...

    async def count_by_room(self, start: dt.date, end: dt.date) -> dict[UUID, int]:
        """Count scheduled lessons per room between two dates (inclusive)."""
        ...

    async def detach_entry(self, entry_id: UUID, now: dt.datetime) -> list[UUID]:
        """Prepare an entry for deletion.

        Future lessons not changed by hand are deleted, or cancelled if they have
        content; every other lesson of the entry is kept without the entry.
        Returns the ids of lessons deleted or cancelled.
        """
        ...
